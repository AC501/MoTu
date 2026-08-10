import pandas as pd
import geopandas as gpd
import os
from datetime import datetime
from gotrackit.map.Net import Net
from gotrackit.MapMatch import MapMatch
from pyproj import Geod
import json

# 路径配置
LINK_FILE = r"D:\xiangmu\motu\gotrackit\input\road\link.gpkg"
NODE_FILE = r"D:\xiangmu\motu\gotrackit\input\road\node.gpkg"
GPS_FILE = r"D:\xiangmu\motu\gotrackit\input\04_convert.csv"
OUT_FOLDER = r"D:\xiangmu\motu\gotrackit\output"

# 读取并预处理GPS
gps_df = pd.read_csv(GPS_FILE).rename(columns={
    'traj_id': 'agent_id', 'longitude': 'lng', 'latitude': 'lat', 'locate_time': 'time'
})
if 'point_id' not in gps_df.columns:
    raise ValueError("缺少 point_id 列")
gps_df = gps_df.sort_values(['agent_id', 'time']).reset_index(drop=True)
gps_df['seq'] = gps_df.groupby('agent_id').cumcount()
point_id_map = gps_df[['agent_id', 'seq', 'point_id']].copy()
gps_df['time'] = pd.to_datetime(gps_df['time']).dt.strftime('%Y-%m-%d %H:%M:%S')
print(f"轨迹数：{gps_df['agent_id'].nunique()}，总点数：{len(gps_df)}")

# 读取路网
link = gpd.read_file(LINK_FILE).to_crs('EPSG:4326')
node = gpd.read_file(NODE_FILE).to_crs('EPSG:4326')
if 'osm_id' not in link.columns:
    raise RuntimeError("link.gpkg 缺少 osm_id")

# 检查路网是否包含限速字段（用于 st-match）
speed_field = 'max_speed'  # 请根据实际路网字段名调整，常见有 'maxspeed', 'speed_limit' 等
if speed_field not in link.columns:
    print(f"警告：路网中未找到限速字段 '{speed_field}'，st-match 将无法使用速度约束。")
    use_st = False
else:
    use_st = True
    print(f"已检测到限速字段 '{speed_field}'，将启用 st-match。")

# 构建路网
my_net = Net(link_gdf=link, node_gdf=node, not_conn_cost=500)
my_net.init_net()

# 匹配（启用 st-match）
mpm = MapMatch(
    net=my_net,
    flag_name='chengdu_match',
    gps_buffer=15,
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
    use_st=use_st,  # 根据路网是否有限速字段决定是否启用

)
match_res, warn_info, error_info = mpm.execute(gps_df=gps_df)
print(f"匹配结果行数：{len(match_res)}")

# 合并 point_id (如果缺失)
if 'point_id' not in match_res.columns:
    if 'agent_id' not in match_res.columns:
        if 'traj_id' in match_res.columns:
            match_res.rename(columns={'traj_id': 'agent_id'}, inplace=True)
        else:
            # 通过 seq 合并
            seq_agent = gps_df[['seq', 'agent_id']].drop_duplicates('seq')
            match_res = match_res.merge(seq_agent, on='seq', how='left')
    match_res['agent_id'] = match_res['agent_id'].astype(str)
    point_id_map['agent_id'] = point_id_map['agent_id'].astype(str)
    merged = match_res.merge(point_id_map, on=['agent_id', 'seq'], how='left')
    if 'point_id' in merged.columns:
        match_res['point_id'] = merged['point_id']
    else:
        # 备用：顺序分配
        if len(match_res) == len(gps_df):
            match_res_sorted = match_res.sort_values(['agent_id', 'seq']).reset_index(drop=True)
            gps_sorted = gps_df.sort_values(['agent_id', 'seq']).reset_index(drop=True)
            if (match_res_sorted['agent_id'] == gps_sorted['agent_id']).all() and \
                    (match_res_sorted['seq'] == gps_sorted['seq']).all():
                match_res['point_id'] = gps_sorted['point_id'].values
        else:
            raise RuntimeError("无法合并 point_id")

# 合并 osm_id 并计算距离
link_id_osm = link[['link_id', 'osm_id']].copy()
match_res = match_res.merge(link_id_osm, on='link_id', how='left')

geod = Geod(ellps='WGS84')


def calc_dist(row):
    try:
        lon1, lat1 = float(row['lng']), float(row['lat'])
        if 'prj_lng' in row and pd.notna(row['prj_lng']):
            lon2, lat2 = float(row['prj_lng']), float(row['prj_lat'])
        else:
            lon2, lat2 = float(row.get('matched_lon', 0)), float(row.get('matched_lat', 0))
        _, _, dist = geod.inv(lon1, lat1, lon2, lat2)
        return dist
    except:
        return None


match_res['distance'] = match_res.apply(calc_dist, axis=1)

# 重命名与整理
match_res.rename(
    columns={'prj_lat': 'matched_lat', 'prj_lng': 'matched_lon', 'time': 'match_time', 'osm_id': 'osm_segment_id'},
    inplace=True)
match_res.insert(0, 'match_id', range(1, len(match_res) + 1))
match_res['confidence'] = 1.0
match_res['distance'] = pd.to_numeric(match_res['distance'], errors='coerce')

# 经纬度格式化
for col in ['lng', 'lat', 'matched_lat', 'matched_lon']:
    if col in match_res.columns:
        match_res[col] = match_res[col].round(7).apply(lambda x: f"{x:.7f}")

# 保留目标列
target_cols = ['match_id', 'point_id', 'agent_id', 'osm_segment_id', 'matched_lat', 'matched_lon', 'distance',
               'confidence', 'match_time']
match_res_export = match_res[target_cols].copy()

# 保存CSV
os.makedirs(OUT_FOLDER, exist_ok=True)
out_csv = os.path.join(OUT_FOLDER, "match_result04.csv")
match_res_export.to_csv(out_csv, encoding='utf_8_sig', index=False)
print(f"结果已保存至 {out_csv}，共 {len(match_res_export)} 行")

# 输出警告统计
warn_cnt = len(warn_info) if isinstance(warn_info, (list, tuple)) else 0
err_cnt = len(error_info) if isinstance(error_info, (list, tuple)) else 0
print(f"警告数：{warn_cnt}，错误数：{err_cnt}")

# 生成完整匹配路径 GeoJSON（用于 kepler.gl）
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

# 导出 kepler.gl HTML（如果安装）
try:
    from keplergl import KeplerGl

    kmap = KeplerGl(height=800)
    kmap.add_data(data=geojson, name='matched_path_full')

    # GPS原始点
    gps_pts = gps_df[['lng', 'lat', 'point_id', 'agent_id', 'seq']].dropna().drop_duplicates(['lng', 'lat'])
    kmap.add_data(data=gps_pts, name='gps_points')

    # 匹配后的点
    matched_pts = match_res[['matched_lon', 'matched_lat', 'point_id', 'agent_id', 'seq']].copy()
    matched_pts = matched_pts.dropna(subset=['matched_lon', 'matched_lat'])
    matched_pts = matched_pts.drop_duplicates(['matched_lon', 'matched_lat']).reset_index(drop=True)
    kmap.add_data(data=matched_pts, name='matched_points')

    kmap.save_to_html(os.path.join(OUT_FOLDER, f'kepler_matched_{timestamp}.html'))
    print("kepler.gl HTML 已生成")
except Exception as e:
    print("kepler.gl 未安装或生成失败：", e)

print("全部处理完成。")