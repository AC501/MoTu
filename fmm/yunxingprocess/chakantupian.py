# -*- coding: utf-8 -*-
import os
import sys
import csv
import pandas as pd
import geopandas as gpd
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from shapely import wkt
from shapely.geometry import Point

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'KaiTi', 'Arial Unicode MS']
plt.rcParams['axes.unicode_minus'] = False
csv.field_size_limit(sys.maxsize)

# ================= 配置区 =================
INPUT_FILE = r"D:\xiangmu\other\input\cleaned_output_6\cleaned_trajectories_wkt.csv"   # 所有原始轨迹（用于ID映射和查询）
RAW_POINTS_FILE = r"D:\xiangmu\other\input\cleaned_output_6\sampled_original.csv"      # 原始未抽稀GPS点（用于提取蓝点）
MATCH_TXT = r"D:\xiangmu\other\input\cleaned_output_6\result_sample300osm.txt"           # 匹配结果文件（可能缺失部分轨迹）
OUTPUT_DIR = r"D:\xiangmu\other\input\trajectory_plots_stmatch_300sample_osm"                 # 输出目录（建议新建一个，避免覆盖）
ROAD_SHP_PATH = r"D:\xiangmu\other\gaode\gd\gd.shp"

os.makedirs(OUTPUT_DIR, exist_ok=True)
# ============================================

print(">>> 1. 读取数据文件...")
# 读取所有原始轨迹（清洗后的）
df_input = pd.read_csv(INPUT_FILE, sep=None, engine='python', encoding='utf-8-sig')
# 读取匹配结果
df_match = pd.read_csv(MATCH_TXT, sep=None, engine='python', dtype=str, encoding='utf-8-sig')

# 将匹配结果中的 id 转为数值并排序（仅用于内部处理，不影响循环）
df_match['id'] = pd.to_numeric(df_match['id'], errors='coerce')
df_match = df_match.sort_values(by='id', ascending=True).reset_index(drop=True)

# 构建一个字典，方便根据 id 快速查找匹配线 WKT
match_dict = {}
for _, row in df_match.iterrows():
    match_dict[str(row['id'])] = row['mgeom']  # 假设 mgeom 列名为 'mgeom'

print(f"原始轨迹总数：{len(df_input)}，匹配结果总数：{len(df_match)}")

# 解析 WKT 的辅助函数（用于将匹配线 WKT 转为 GeoDataFrame）
def parse_wkt_series(df, geom_col):
    geoms = []
    for w in df[geom_col]:
        try:
            geoms.append(wkt.loads(w))
        except:
            geoms.append(None)
    sub_df = df.copy()
    sub_df['geometry'] = geoms
    gdf = gpd.GeoDataFrame(sub_df, geometry='geometry', crs="EPSG:4326")
    return gdf.dropna(subset=['geometry'])

# 提取原始未抽稀的 GPS 点（蓝点）
print(f">>> 正在从 {RAW_POINTS_FILE} 提取原始未抽稀点...")
df_raw_points = pd.read_csv(RAW_POINTS_FILE, sep=None, engine='python', encoding='utf-8-sig')
points_list = []
for _, row in df_raw_points.iterrows():
    try:
        line = wkt.loads(row['geometry'])  # 原始线 WKT
        traj_id = str(row['id'])           # 长轨迹ID
        for coord in line.coords:
            points_list.append({
                'traj_id': traj_id,
                'geometry': Point(coord)
            })
    except:
        continue

gdf_points = gpd.GeoDataFrame(points_list, geometry='geometry', crs="EPSG:4326")
print(f"成功提取 {len(gdf_points)} 个原始未抽稀的轨迹点。")

# ================= 加载高德路网底图 =================
print(f">>> 2. 加载高德路网底图：{ROAD_SHP_PATH}")
try:
    road_gdf = gpd.read_file(ROAD_SHP_PATH)
    if road_gdf.crs != gdf_points.crs:
        road_gdf = road_gdf.to_crs(gdf_points.crs)
except Exception as e:
    print(f"警告：高德路网加载失败，将不显示底图，错误：{e}")
    road_gdf = None

print(">>> 3. 开始逐条轨迹绘图（包括未匹配的轨迹）...")

total = len(df_input)
count = 0
unmatched_count = 0  # 统计未匹配的轨迹数

for _, row in df_input.iterrows():
    traj_id_short = str(row['id'])          # 短ID（用于匹配结果查找）
    original_traj_id = str(row['traj_id'])  # 长ID（用于提取GPS点）

    # 1. 提取当前轨迹的原始GPS点（蓝点）
    pts_traj = gdf_points[gdf_points['traj_id'].astype(str) == traj_id_short].copy()
    if pts_traj.empty:
        # 如果没有GPS点，跳过（理论上不应发生）
        continue

    # 2. 检查是否有匹配结果
    match_wkt = match_dict.get(traj_id_short)  # 获取匹配线的 WKT
    has_match = match_wkt is not None

    # 如果有匹配线，解析为 GeoDataFrame
    if has_match:
        # 构造一个临时 DataFrame 以调用 parse_wkt_series
        temp_df = pd.DataFrame({'id': [traj_id_short], 'mgeom': [match_wkt]})
        match_traj = parse_wkt_series(temp_df, 'mgeom')
    else:
        match_traj = gpd.GeoDataFrame()  # 空的 GeoDataFrame
        unmatched_count += 1

    # ========== 计算边界范围 ==========
    bounds_list = []
    if not pts_traj.empty:
        bounds_list.append(pts_traj.total_bounds)
    if not match_traj.empty:
        bounds_list.append(match_traj.total_bounds)

    if not bounds_list:
        continue

    minx = min(b[0] for b in bounds_list)
    miny = min(b[1] for b in bounds_list)
    maxx = max(b[2] for b in bounds_list)
    maxy = max(b[3] for b in bounds_list)

    margin_x = (maxx - minx) * 0.1 if maxx > minx else 0.001
    margin_y = (maxy - miny) * 0.1 if maxy > miny else 0.001

    ax_minx, ax_maxx = minx - margin_x, maxx + margin_x
    ax_miny, ax_maxy = miny - margin_y, maxy + margin_y

    # ★★★ 创建画布 ★★★
    fig, ax = plt.subplots(figsize=(10, 10))
    ax.set_xlim(ax_minx, ax_maxx)
    ax.set_ylim(ax_miny, ax_maxy)

    # 绘制高德路网底图
    if road_gdf is not None:
        local_roads = road_gdf.cx[ax_minx:ax_maxx, ax_miny:ax_maxy]
        if len(local_roads) > 0:
            local_roads.plot(ax=ax, color='lightgray', linewidth=0.5, zorder=1)

    # 绘制原始的蓝色轨迹点
    if not pts_traj.empty:
        pts_traj.plot(ax=ax, color='blue', markersize=15, label='原始GPS点', zorder=2)

    # 如果有匹配结果，绘制红色匹配线
    if not match_traj.empty:
        match_traj.plot(ax=ax, color='red', linewidth=2.5, linestyle='--', label='ST-Match匹配线', zorder=3)

    # ★★★ 设置标题 ★★★
    title = f"Trajectory {traj_id_short} (原始ID: {original_traj_id})"
    if not has_match:
        title += " [未匹配]"
    ax.set_title(title, fontsize=14)
    ax.legend()
    ax.axis('off')

    plt.tight_layout()
    save_path = os.path.join(OUTPUT_DIR, f"traj_{traj_id_short}.png")
    plt.savefig(save_path, dpi=150)
    plt.close(fig)

    count += 1
    if count % 5 == 0:
        print(f"已处理 {count}/{total} 条轨迹...")

print(f">>> 可视化完成！共生成 {count} 张图片，保存于：{OUTPUT_DIR}")
print(f"其中未匹配的轨迹数为：{unmatched_count}")