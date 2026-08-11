#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
FMM 匹配结果解析脚本

功能：
  从原始GPS点文件（traj_all_continuous_ready.csv）和FMM输出文件（result_all.txt）中，
  提取每个点的匹配结果，计算匹配偏差，生成标准化的匹配结果表。

输入文件：
  - traj_all_continuous_ready.csv : 原始GPS点数据（分号分隔）
  - result_all.txt : FMM匹配输出结果（分号分隔）

输出文件：
  - full_match_result_all.csv : 完整匹配结果表，包含12个字段
"""

import csv
import re
from math import radians, sin, cos, sqrt, atan2


def haversine(lon1, lat1, lon2, lat2):
    """
    计算两个经纬度点之间的球面距离（Haversine公式）

    参数:
        lon1, lat1 : 第一个点的经度、纬度（度）
        lon2, lat2 : 第二个点的经度、纬度（度）

    返回值:
        两点之间的球面距离（米）
    """
    R = 6371000  # 地球平均半径（米）
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)

    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def distance_range(dist):
    """
    根据偏移距离（米）映射到分段标签

    参数:
        dist : 偏移距离（米）

    返回值:
        对应的距离区间字符串（如 "0-5m", "5-10m", ...）
    """
    if dist < 0:
        return "无效"
    elif dist < 5:
        return "0-5m"
    elif dist < 10:
        return "5-10m"
    elif dist < 20:
        return "10-20m"
    elif dist < 30:
        return "20-30m"
    elif dist < 50:
        return "30-50m"
    else:
        return "≥50m"


# ============================================================
# 步骤1：读取原始GPS点信息，建立 pid → 点信息 的映射
# ============================================================
print("读取原始点信息...")
point_info = {}

with open('traj_all_continuous_ready.csv', 'r') as f:
    reader = csv.reader(f, delimiter=';')
    header = next(reader)  # 跳过表头

    for row in reader:
        if len(row) < 6:
            continue

        pid = int(row[0])           # 全局连续ID（FMM中的traj_id）
        orig_traj_id = row[1]       # 原始轨迹ID（agent_id）
        orig_point_id = row[2]      # 原始点ID（追溯原始数据用）
        lon = float(row[3])         # 原始经度
        lat = float(row[4])         # 原始纬度
        ts = row[5]                 # 时间戳

        point_info[pid] = {
            'orig_traj_id': orig_traj_id,
            'orig_point_id': orig_point_id,
            'lon': lon,
            'lat': lat,
            'timestamp': ts
        }

print(f"读取了 {len(point_info)} 个点")


# ============================================================
# 步骤2：解析FMM输出文件
# ============================================================
print("解析 FMM 结果...")
records = []

with open('result_all.txt', 'r') as f_in:
    # 读取并解析表头，建立列名 → 索引的映射
    header_line = f_in.readline().strip().split(';')
    col_idx = {col: i for i, col in enumerate(header_line)}

    # 关键列的索引（如果列名不存在，使用默认值）
    traj_id_col = col_idx.get('traj_id', 0)   # 轨迹ID（对应pid）
    cpath_col = col_idx.get('cpath', 6)       # 匹配到的路段ID序列
    mgeom_col = col_idx.get('mgeom', 8)       # 匹配后的路径几何（LINESTRING WKT）

    for line in f_in:
        parts = line.strip().split(';')

        # 确保行有足够的字段
        if len(parts) <= max(traj_id_col, cpath_col, mgeom_col):
            continue

        # 提取关键字段
        traj_id = int(parts[traj_id_col])    # 全局连续ID
        cpath = parts[cpath_col]             # 路段ID列表，逗号分隔
        mgeom = parts[mgeom_col]             # WKT LINESTRING

        # 如果 mgeom 为空或 NULL，说明该点未匹配，跳过
        if not mgeom or mgeom == 'NULL':
            continue

        # 从 mgeom 中提取匹配点坐标（格式: "lon1 lat1, lon2 lat2, ..."）
        coords = re.findall(r'([0-9.]+)\s+([0-9.]+)', mgeom)

        # 解析路段ID列表
        edge_ids = [int(x) for x in cpath.split(',') if x.strip()] if cpath else []

        if not coords:
            continue

        # 通过 traj_id 查找原始点信息
        info = point_info.get(traj_id)
        if not info:
            continue

        orig_lon = info['lon']
        orig_lat = info['lat']
        orig_traj_id = info['orig_traj_id']
        orig_point_id = info['orig_point_id']
        timestamp = info['timestamp']

        # 遍历每个匹配点坐标（一个mgeom中可能包含多个点）
        for i, (lon_str, lat_str) in enumerate(coords):
            matched_lon = float(lon_str)
            matched_lat = float(lat_str)

            # 计算原始点到匹配点的偏移距离（米）
            dist = haversine(orig_lon, orig_lat, matched_lon, matched_lat)

            # 获取对应的路段ID（如果超出则设为 -1）
            osm_id = edge_ids[i] if i < len(edge_ids) else -1

            # 基于距离计算置信度（距离越小，置信度越高）
            # 公式: confidence = 1 / (1 + dist/10)，dist=0时置信度为1
            confidence = 1.0 / (1.0 + dist / 10)

            # 组装记录
            records.append({
                'point_id': traj_id,                # 全局连续ID（FMM中的traj_id）
                'orig_point_id': orig_point_id,     # 原始点ID
                'agent_id': orig_traj_id,           # 原始轨迹ID
                'osm_segment_id': osm_id,           # 匹配到的OSM路段ID
                'lng': orig_lon,                    # 原始经度
                'lat': orig_lat,                    # 原始纬度
                'matched_lon': matched_lon,         # 匹配点经度
                'matched_lat': matched_lat,         # 匹配点纬度
                'distance': dist,                   # 偏移距离（米）
                'confidence': confidence,           # 置信度（0-1）
                'match_time': timestamp,            # 匹配时间戳
                'distance_range': distance_range(dist)  # 距离分段标签
            })

print(f"共解析出 {len(records)} 条记录，正在排序...")


# ============================================================
# 步骤3：排序
# ============================================================
# 按 agent_id（原始轨迹ID）和 point_id（全局连续ID）排序
# 这样同一轨迹的所有点会连续排列，便于后续按轨迹分组分析
records_sorted = sorted(records, key=lambda r: (r['agent_id'], r['point_id']))


# ============================================================
# 步骤4：输出最终结果表
# ============================================================
print("输出最终结果表...")

with open('full_match_result_all.csv', 'w', newline='') as f:
    writer = csv.writer(f, delimiter=';')

    # 写入表头（12个字段）
    writer.writerow([
        'match_id',         # 匹配记录ID（自增，从1开始）
        'point_id',         # 全局连续ID（FMM中的traj_id）
        'orig_point_id',    # 原始点ID
        'agent_id',         # 原始轨迹ID
        'osm_segment_id',   # 匹配到的OSM路段ID（-1表示未匹配）
        'lng',              # 原始点经度
        'lat',              # 原始点纬度
        'matched_lon',      # 匹配点经度
        'matched_lat',      # 匹配点纬度
        'distance',         # 原始点到匹配点的偏移距离（米）
        'confidence',       # 置信度（0-1）
        'match_time',       # 时间戳
        'distance_range'    # 偏移距离分段标签
    ])

    # 逐行写入数据，match_id 从1开始递增
    for idx, rec in enumerate(records_sorted, start=1):
        writer.writerow([
            idx,
            rec['point_id'],
            rec['orig_point_id'],
            rec['agent_id'],
            rec['osm_segment_id'],
            rec['lng'],
            rec['lat'],
            rec['matched_lon'],
            rec['matched_lat'],
            rec['distance'],
            rec['confidence'],
            rec['match_time'],
            rec['distance_range']
        ])

print(f" 结果表已生成: full_match_result_all.csv，共 {len(records_sorted)} 条记录")