import geopandas as gpd

# 读取路网
link = gpd.read_file("D:/xiangmu/other/input/road/link.gpkg")
node = gpd.read_file("D:/xiangmu/other/input/road/node.gpkg")

# 检查坐标系
print(link.crs)  # 应为 EPSG:4326

# 检查必备字段
required_link_fields = ['osm_id', 'from_node', 'to_node', 'geometry']
for field in required_link_fields:
    if field not in link.columns:
        print(f"路段层缺少字段: {field}")

required_node_fields = ['node_id', 'geometry']
for field in required_node_fields:
    if field not in node.columns:
        print(f"节点层缺少字段: {field}")