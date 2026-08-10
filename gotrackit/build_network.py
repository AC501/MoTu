import pandas as pd
import geopandas as gpd
from sqlalchemy import create_engine
from shapely.geometry import LineString
import gotrackit.netreverse.NetGen as ng

# 数据库配置（请修改为实际参数）
DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD = "localhost", "5432", "motu", "postgres", "root"
TABLE_NAME = "osm_road_segment"
OUT_FOLDER = r"D:\xiangmu\motu\gotrackit\input\road"

engine = create_engine(f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}")

print("读取道路...")
road = gpd.read_postgis(
    f"SELECT osm_id, oneway, geometry, max_speed FROM {TABLE_NAME}",
    con=engine,
    geom_col='geometry'
)

road = road.to_crs("EPSG:4326").dropna(subset=['geometry']).explode(ignore_index=True)
road['osm_id'] = road['osm_id'].astype('int64')
road['max_speed'] = pd.to_numeric(road['max_speed'], errors='coerce')  # 转为数值

def parse_dir(v):
    if pd.isna(v):
        return 0
    v = str(v).strip().lower()
    return -1 if v == '-1' else (1 if v in ('yes','1','true') else 0)

road["dir"] = road["oneway"].apply(parse_dir)
reverse_idx = road["dir"] == -1
road.loc[reverse_idx, "geometry"] = road.loc[reverse_idx, "geometry"].apply(
    lambda line: LineString(list(line.coords)[::-1])
)
road.loc[reverse_idx, "dir"] = 1

print("清洗几何...")
road = ng.NetReverse.clean_link_geo(road, plain_crs='EPSG:32648', l_threshold=0.3)

print("生成拓扑...")
link_gdf, node_gdf, _ = ng.NetReverse.create_node_from_link(
    link_gdf=road,
    using_from_to=False,
    update_link_field_list=["link_id", "from_node", "to_node", "length", "dir"],
    plain_crs="EPSG:32648",
    execute_modify=True,
    modify_minimum_buffer=0.3,
    ignore_merge_rule=True,
    out_fldr=None,
    auxiliary_judge_field='dir'
)

# 恢复 osm_id
if 'osm_id_0' in link_gdf.columns:
    link_gdf.rename(columns={'osm_id_0': 'osm_id'}, inplace=True)

# 确保 max_speed 保留
if 'max_speed' not in link_gdf.columns:
    link_gdf = link_gdf.merge(road[['osm_id', 'max_speed']].drop_duplicates('osm_id'), on='osm_id', how='left')

print(f"路段数：{len(link_gdf)}，节点数：{len(node_gdf)}")
print("link_gdf 列名：", link_gdf.columns.tolist())

link_gdf.to_file(OUT_FOLDER + r"\link.gpkg", driver="GPKG")
node_gdf.to_file(OUT_FOLDER + r"\node.gpkg", driver="GPKG")
print("路网构建完成。")