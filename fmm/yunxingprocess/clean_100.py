import os
import csv
import random
import pandas as pd
import geopandas as gpd
import numpy as np
from shapely.geometry import Point, LineString
from shapely.wkt import loads
import movingpandas as mpd
from scipy.spatial import KDTree

# ============ 可调参数 ============
INPUT_CSV = r"D:\xiangmu\other\input\10-20\traj_input_10-20.csv"  # 原始轨迹文件
SAMPLE_SIZE = 10                                 # 抽取轨迹条数
OUTPUT_DIR = "cleaned_output_8"                     # 输出目录
TOLERANCE_METERS = 5                              # 抽稀容差（米）
MIN_POINTS_RATIO = 0.1                            # 抽稀后最少保留比例
# ===================================

os.makedirs(OUTPUT_DIR, exist_ok=True)

# 1. 读取并抽取
print(f"1. 从 {INPUT_CSV} 中随机抽取 {SAMPLE_SIZE} 条轨迹...")
df_input = pd.read_csv(INPUT_CSV, delimiter=";")
if len(df_input) < SAMPLE_SIZE:
    print(f"⚠️ 文件只有 {len(df_input)} 条，全部使用。")
    sampled_df = df_input
else:
    sampled_df = df_input.sample(n=SAMPLE_SIZE, random_state=None)
sampled_df.reset_index(drop=True, inplace=True)
sampled_df['short_id'] = range(1, len(sampled_df)+1)
sampled_df.to_csv(os.path.join(OUTPUT_DIR, "sampled_original.csv"), sep=";", index=False)

# 2. 拆点
print("2. 拆点...")
points_file = os.path.join(OUTPUT_DIR, "points_for_cleaning.csv")
with open(points_file, "w", encoding="utf-8", newline="") as f:
    writer = csv.writer(f, delimiter=";")
    writer.writerow(["traj_id", "lng", "lat", "timestamp"])
    for _, row in sampled_df.iterrows():
        traj_id = row["id"]
        line = loads(row["geometry"])
        coords = list(line.coords)
        timestamps = row["timestamp"].split(",")
        n = min(len(coords), len(timestamps))
        for i in range(n):
            writer.writerow([traj_id, coords[i][0], coords[i][1], timestamps[i].strip()])

# 3. 速度过滤
print("3. 速度过滤...")
df_pts = pd.read_csv(points_file, delimiter=";")
df_pts['timestamp'] = pd.to_datetime(df_pts['timestamp'], unit='s')
gdf = gpd.GeoDataFrame(df_pts, geometry=gpd.points_from_xy(df_pts.lng, df_pts.lat), crs="EPSG:4326")
traj_collection = mpd.TrajectoryCollection(gdf, traj_id_col='traj_id', t='timestamp')
cleaned = mpd.OutlierCleaner(traj_collection).clean(v_max=120, units=("km", "h"))
filtered = [traj for traj in cleaned if traj.df.shape[0] >= 3]
if not filtered:
    print("⚠️ 没有轨迹通过速度过滤，退出。")
    exit()
cleaned_collection = mpd.TrajectoryCollection(filtered)
print(f"   速度过滤后轨迹数: {len(cleaned_collection)}")

# 4. 抽稀（Shapely simplify，与用户脚本逻辑一致）
print(f"4. 道格拉斯-普克抽稀（容差={TOLERANCE_METERS}米）...")
tolerance_deg = TOLERANCE_METERS / 111320
simplified_trajs = []
for traj in cleaned_collection:
    df_traj = traj.df
    coords = [(p.x, p.y) for p in df_traj.geometry]
    orig_n = len(coords)
    if orig_n < 5:
        simplified_trajs.append(traj)
        continue
    line = LineString(coords)
    simplified_line = line.simplify(tolerance=tolerance_deg, preserve_topology=True)
    new_coords = list(simplified_line.coords)
    new_n = len(new_coords)
    if new_n < max(5, int(orig_n * MIN_POINTS_RATIO)):
        print(f"   轨迹 {traj.id}: 原始{orig_n}点，抽稀后{new_n}点，保留原轨迹")
        simplified_trajs.append(traj)
        continue
    # 最近邻时间戳
    orig_xy = np.array(coords)
    tree = KDTree(orig_xy)
    new_points = []
    for x, y in new_coords:
        dist, idx = tree.query([x, y])
        row = df_traj.iloc[idx]
        new_points.append({'geometry': Point(x, y), 'timestamp': row.name})
    new_gdf = gpd.GeoDataFrame(new_points, geometry='geometry', crs="EPSG:4326")
    new_gdf = new_gdf.set_index('timestamp')
    try:
        new_traj = mpd.Trajectory(new_gdf, traj_id=traj.id)
    except TypeError:
        new_traj = mpd.Trajectory(new_gdf)
    simplified_trajs.append(new_traj)

if not simplified_trajs:
    print("⚠️ 抽稀后无轨迹。")
    exit()
final = mpd.TrajectoryCollection(simplified_trajs)
print(f"   抽稀后轨迹数: {len(final)}")

# 5. 导出清洗后点数据和WKT
print("5. 导出清洗后WKT...")
all_points = []
for traj in final:
    gdf_traj = traj.df.reset_index()
    gdf_traj.rename(columns={'index': 'timestamp'}, inplace=True)
    gdf_traj['traj_id'] = traj.id
    gdf_traj['lng'] = gdf_traj.geometry.x
    gdf_traj['lat'] = gdf_traj.geometry.y
    all_points.append(gdf_traj[['traj_id', 'lng', 'lat', 'timestamp']])
cleaned_df = pd.concat(all_points, ignore_index=True)

# 短ID映射
short_id_map = dict(zip(sampled_df['id'], sampled_df['short_id']))

def build_wkt(group):
    coords = list(zip(group['lng'], group['lat']))
    line = LineString(coords)
    unix_ts = group['timestamp'].astype('int64') // 10**9
    timestamps = ','.join(unix_ts.astype(str))
    short_id = short_id_map.get(group.name, group.name)
    return pd.Series({
        'traj_id': group.name,
        'id': short_id,
        'geometry': line.wkt,
        'timestamp': timestamps
    })

result = cleaned_df.groupby('traj_id').apply(build_wkt).reset_index(drop=True)
clean_wkt_file = os.path.join(OUTPUT_DIR, "cleaned_trajectories_wkt.csv")
result.to_csv(clean_wkt_file, sep=";", index=False)
print(f"✅ 清洗完成，输出文件: {clean_wkt_file}")
print(f"   请在 Cygwin 中执行 FMM 匹配，指定 --gps_id id（长ID）。")