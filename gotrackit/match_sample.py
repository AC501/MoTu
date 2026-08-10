import warnings

import pandas as pd
import geopandas as gpd
import os
from datetime import datetime
from gotrackit.map.Net import Net
from gotrackit.MapMatch import MapMatch
from sqlalchemy import create_engine
import json
import numpy as np
import math   # 用于坐标转换



warnings.filterwarnings("ignore", category=UserWarning, module="gotrackit")
# ===================================================
# 坐标转换函数（GCJ-02 → WGS-84）
# ===================================================
def out_of_china(lng, lat):
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)

def transform_lat(x, y):
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret

def transform_lng(x, y):
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret

def gcj02_to_wgs84(lng, lat):
    if out_of_china(lng, lat):
        return lng, lat
    a = 6378245.0
    ee = 0.00669342162296594323
    dlat = transform_lat(lng - 105.0, lat - 35.0)
    dlng = transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrt_magic) * math.pi)
    dlng = (dlng * 180.0) / (a / sqrt_magic * math.cos(radlat) * math.pi)
    mg_lat = lat + dlat
    mg_lng = lng + dlng
    return lng * 2 - mg_lng, lat * 2 - mg_lat

# ===================================================
# 配置参数
# ===================================================
# ----- 数据库连接 -----
DB_HOST = "localhost"
DB_PORT = "5432"
DB_NAME = "motu"
DB_USER = "postgres"
DB_PASSWORD = "root"

# ----- 随机抽取轨迹数量 -----
TRAJECTORY_LIMIT = 5000   # 可改为 5, 10, 100 等

# ----- 路网路径 -----
LINK_FILE = r"D:\xiangmu\motu\gotrackit\input\road\link.gpkg"
NODE_FILE = r"D:\xiangmu\motu\gotrackit\input\road\node.gpkg"
OUT_FOLDER = r"D:\xiangmu\motu\gotrackit\output"

# ===================================================
# 连接数据库
# ===================================================
engine = create_engine(f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")

# ===================================================
# 从数据库读取轨迹数据（使用提供的 SQL）
# ===================================================
print("从数据库读取轨迹数据...")
sql = f"""
WITH random_traj_ids AS (
    SELECT traj_id
    FROM (
        SELECT DISTINCT traj_id
        FROM trajectory_point_raw
    ) AS distinct_traj
    ORDER BY RANDOM()
    LIMIT {TRAJECTORY_LIMIT}
)
SELECT 
    tp.point_id,
    tp.traj_id AS agent_id,
    tp.longitude AS lng,
    tp.latitude AS lat,
    TO_CHAR(tp.locate_time, 'YYYY-MM-DD HH24:MI:SS') AS time,
    tp.bearing,
    tp.speed
FROM 
    trajectory_point_raw tp
INNER JOIN 
    random_traj_ids rti ON tp.traj_id = rti.traj_id
ORDER BY 
    tp.traj_id, tp.locate_time;
"""

gps_df = pd.read_sql_query(sql, con=engine)
print(f"读取完成！轨迹数：{gps_df['agent_id'].nunique()}，总点数：{len(gps_df)}")
print("列名：", gps_df.columns.tolist())

# ===================================================
# 坐标转换：火星坐标（GCJ-02）→ WGS-84
# ===================================================
print("正在进行坐标转换（GCJ-02 → WGS-84）...")
gps_df[['lng', 'lat']] = gps_df.apply(
    lambda row: gcj02_to_wgs84(row['lng'], row['lat']),
    axis=1,
    result_type='expand'
)
print("坐标转换完成。")

# ===================================================
# 后续处理与原代码完全一致（无需修改）
# ===================================================
# 注意：原代码中已经有生成 seq、point_id_map、时间格式化等
# 但我们的 SQL 中已经包含 point_id 和 time，且 time 已格式化，
# 但为了统一，仍保留原有的预处理步骤（可安全执行）

if 'point_id' not in gps_df.columns:
    raise ValueError("缺少 point_id 列")

# 按 agent_id 和 time 排序（已由 SQL ORDER BY 保证，但为确保安全重新排序）
gps_df = gps_df.sort_values(['agent_id', 'time']).reset_index(drop=True)
# 重新生成 seq（因为可能因排序变化，但 SQL 已经按时间排序，所以直接 cumcount 即可）
gps_df['seq'] = gps_df.groupby('agent_id').cumcount()
# 保存 point_id 映射
point_id_map = gps_df[['agent_id', 'seq', 'point_id']].copy()
# 时间格式化为字符串（已由 SQL 转换，但再确保一次）
gps_df['time'] = pd.to_datetime(gps_df['time']).dt.strftime('%Y-%m-%d %H:%M:%S')
print(f"轨迹数：{gps_df['agent_id'].nunique()}，总点数：{len(gps_df)}")

# ========== 以下代码与原完全一致 ==========
# 读取路网（并按轨迹范围过滤，降低内存）
print("读取路网...")
link = gpd.read_file(LINK_FILE).to_crs('EPSG:4326')
node = gpd.read_file(NODE_FILE).to_crs('EPSG:4326')
if 'osm_id' not in link.columns:
    raise RuntimeError("link.gpkg 缺少 osm_id")

# 空间过滤
buffer_deg = 0.05
min_lon = gps_df['lng'].min() - buffer_deg
max_lon = gps_df['lng'].max() + buffer_deg
min_lat = gps_df['lat'].min() - buffer_deg
max_lat = gps_df['lat'].max() + buffer_deg
print(f"过滤路网范围：经度 [{min_lon:.4f}, {max_lon:.4f}], 纬度 [{min_lat:.4f}, {max_lat:.4f}]")

link = link.cx[min_lon:max_lon, min_lat:max_lat]
if link.empty:
    raise RuntimeError("过滤后路网为空，请检查 GPS 范围或增大 buffer_deg")
used_nodes = set(link['from_node']).union(set(link['to_node']))
node = node[node['node_id'].isin(used_nodes)]
link = link.reset_index(drop=True)
node = node.reset_index(drop=True)
print(f"过滤后路段数：{len(link)}，节点数：{len(node)}")

# 检查限速字段
speed_field = 'max_speed'
if speed_field not in link.columns:
    print(f"警告：路网中未找到限速字段 '{speed_field}'，st-match 将无法使用速度约束。")
    use_st = False
else:
    use_st = True
    print(f"已检测到限速字段 '{speed_field}'，将启用 st-match。")

# 构建路网
my_net = Net(link_gdf=link, node_gdf=node, not_conn_cost=500)
my_net.init_net()

# 匹配（参数保持原样）
mpm = MapMatch(
    net=my_net,
    flag_name='chengdu_match',
    gps_buffer=80,
    top_k=5,
    beta=2,
    gps_sigma=8,
    dis_para=0.5,
    dup_threshold=2,
    time_format='%Y-%m-%d %H:%M:%S',
    use_heading_inf=True,
    omitted_l=5.0,
    export_html=False,
    out_fldr=OUT_FOLDER,
    use_st=use_st,
)
match_res, warn_info, error_info = mpm.execute(gps_df=gps_df)
print(f"匹配结果行数：{len(match_res)}")

# ========== 合并 point_id（如果缺失） ==========
if 'point_id' not in match_res.columns:
    if 'agent_id' not in match_res.columns:
        if 'traj_id' in match_res.columns:
            match_res.rename(columns={'traj_id': 'agent_id'}, inplace=True)
        else:
            seq_agent = gps_df[['seq', 'agent_id']].drop_duplicates('seq')
            match_res = match_res.merge(seq_agent, on='seq', how='left')
    match_res['agent_id'] = match_res['agent_id'].astype(str)
    point_id_map['agent_id'] = point_id_map['agent_id'].astype(str)
    merged = match_res.merge(point_id_map, on=['agent_id', 'seq'], how='left')
    if 'point_id' in merged.columns:
        match_res['point_id'] = merged['point_id']
    else:
        if len(match_res) == len(gps_df):
            match_res_sorted = match_res.sort_values(['agent_id', 'seq']).reset_index(drop=True)
            gps_sorted = gps_df.sort_values(['agent_id', 'seq']).reset_index(drop=True)
            if (match_res_sorted['agent_id'] == gps_sorted['agent_id']).all() and \
                    (match_res_sorted['seq'] == gps_sorted['seq']).all():
                match_res['point_id'] = gps_sorted['point_id'].values
        else:
            raise RuntimeError("无法合并 point_id")

# 合并 osm_id
link_id_osm = link[['link_id', 'osm_id']].copy()
match_res = match_res.merge(link_id_osm, on='link_id', how='left')

# 向量化计算偏移距离
print("计算偏移距离（向量化）...")
lon1 = match_res['lng'].astype(float).values
lat1 = match_res['lat'].astype(float).values

if 'prj_lng' in match_res.columns:
    lon2 = match_res['prj_lng'].astype(float).values
    lat2 = match_res['prj_lat'].astype(float).values
elif 'matched_lon' in match_res.columns:
    lon2 = match_res['matched_lon'].astype(float).values
    lat2 = match_res['matched_lat'].astype(float).values
else:
    raise KeyError("匹配结果中缺少 prj_lng/prj_lat 或 matched_lon/matched_lat，无法计算偏移距离")

lon1_rad = np.radians(lon1)
lat1_rad = np.radians(lat1)
lon2_rad = np.radians(lon2)
lat2_rad = np.radians(lat2)
dlon = lon2_rad - lon1_rad
dlat = lat2_rad - lat1_rad
a = np.sin(dlat/2)**2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon/2)**2
distance = 6371000 * 2 * np.arcsin(np.sqrt(a))
match_res['distance'] = distance

# 重命名与整理
match_res.rename(
    columns={'prj_lat': 'matched_lat', 'prj_lng': 'matched_lon',
             'time': 'match_time', 'osm_id': 'osm_segment_id'},
    inplace=True
)
match_res.insert(0, 'match_id', range(1, len(match_res)+1))

# 动态置信度
match_res['distance'] = pd.to_numeric(match_res['distance'], errors='coerce')
match_res['confidence'] = np.exp(-match_res['distance'] / 30)
match_res['confidence'] = match_res['confidence'].clip(0, 1).fillna(0)

# 经纬度格式化
for col in ['lng', 'lat', 'matched_lat', 'matched_lon']:
    if col in match_res.columns:
        match_res[col] = match_res[col].round(7).apply(lambda x: f"{x:.7f}")

# 保留目标列（增加原始GPS经纬度）
target_cols = ['match_id', 'point_id', 'agent_id', 'osm_segment_id',
               'lng', 'lat',                          # 原始GPS经纬度
               'matched_lon', 'matched_lat',         # 匹配后的经纬度
               'distance', 'confidence', 'match_time']
match_res_export = match_res[target_cols].copy()

# 保存 CSV
os.makedirs(OUT_FOLDER, exist_ok=True)
out_csv = os.path.join(OUT_FOLDER, "match_result03.csv")
match_res_export.to_csv(out_csv, encoding='utf_8_sig', index=False)
print(f"结果已保存至 {out_csv}，共 {len(match_res_export)} 行")

# 警告统计
warn_cnt = len(warn_info) if isinstance(warn_info, (list, tuple)) else 0
err_cnt = len(error_info) if isinstance(error_info, (list, tuple)) else 0
print(f"警告数：{warn_cnt}，错误数：{err_cnt}")

# 生成 GeoJSON
features = []
for agent_id, group in match_res.sort_values(['agent_id', 'seq']).groupby('agent_id'):
    coords = []
    prev = None
    for _, r in group.iterrows():
        try:
            lon = float(r['proj_lon']) if pd.notna(r.get('proj_lon')) else float(r['matched_lon'])
            lat = float(r['proj_lat']) if pd.notna(r.get('proj_lat')) else float(r['matched_lat'])
            pt = (lon, lat)
            if prev is None or pt != prev:
                coords.append(pt)
            prev = pt
        except:
            continue
    if len(coords) > 1:
        features.append({'type': 'Feature', 'properties': {'agent_id': agent_id},
                         'geometry': {'type': 'LineString', 'coordinates': coords}})
geojson = {'type': 'FeatureCollection', 'features': features}
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
with open(os.path.join(OUT_FOLDER, f'matched_path_full_{timestamp}.geojson'), 'w', encoding='utf-8') as f:
    json.dump(geojson, f)

# 导出 kepler.gl HTML
try:
    from keplergl import KeplerGl
    kmap = KeplerGl(height=800)
    kmap.add_data(data=geojson, name='matched_path_full')
    gps_pts = gps_df[['lng','lat','point_id','agent_id','seq']].dropna().drop_duplicates(['lng','lat'])
    kmap.add_data(data=gps_pts, name='gps_points')
    matched_pts = match_res[['matched_lon','matched_lat','point_id','agent_id','seq']].copy()
    matched_pts = matched_pts.dropna(subset=['matched_lon','matched_lat'])
    matched_pts = matched_pts.drop_duplicates(['matched_lon','matched_lat']).reset_index(drop=True)
    kmap.add_data(data=matched_pts, name='matched_points')
    kmap.save_to_html(os.path.join(OUT_FOLDER, f'kepler_matched_{timestamp}.html'))
    print("kepler.gl HTML 已生成")
except Exception as e:
    print("kepler.gl 未安装或生成失败：", e)

print("全部处理完成。")