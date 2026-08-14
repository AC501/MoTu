import pandas as pd
import geopandas as gpd
import numpy as np
import networkx as nx
from shapely.geometry import Point
from shapely.ops import nearest_points
import os
import warnings
warnings.filterwarnings("ignore")

# ===================================================
# 1. 辅助函数：根据相邻 GPS 点计算 bearing
# ===================================================
def add_bearing_from_gps(df):
    """按 agent_id 分组，根据相邻点的经纬度计算 bearing（度）"""
    df = df.sort_values(['agent_id', 'seq']).copy()
    df['bearing'] = np.nan
    for agent_id, group in df.groupby('agent_id'):
        for i in range(len(group) - 1):
            lon1, lat1 = group.iloc[i][['lng', 'lat']]
            lon2, lat2 = group.iloc[i+1][['lng', 'lat']]
            bearing = np.degrees(np.arctan2(lat2 - lat1, lon2 - lon1)) % 360
            df.loc[group.index[i], 'bearing'] = bearing
        if len(group) > 1:
            df.loc[group.index[-1], 'bearing'] = df.loc[group.index[-2], 'bearing']
    return df

# ===================================================
# 2. 候选评分修正函数（含当前匹配评估）
# ===================================================
def correct_abnormal_points(
    df_matched,
    link_gdf,
    node_gdf,
    G,
    abnormal_indices,
    buffer_radius=40,
    alpha=0.05,
    beta=0.85,
    gamma=0.10,
    max_candidates=20,
    use_heading=True,
    debug=False,
    max_dist_factor=1.5,
    context_points=3,
    keep_threshold=0.0
):
    df_corrected = df_matched.copy()
    required = ['agent_id', 'seq', 'lng', 'lat', 'matched_lon', 'matched_lat',
                'osm_segment_id', 'distance']
    for col in required:
        if col not in df_corrected.columns:
            raise ValueError(f"缺少必要字段: {col}")

    has_bearing = ('bearing' in df_corrected.columns) and use_heading
    if has_bearing:
        print("[OK] 使用方向信息（bearing + 上下文方向）进行评分")
    else:
        print("[WARN] 未检测到 bearing，仅使用上下文方向")

    link_gdf_proj = link_gdf
    if link_gdf.crs is not None and link_gdf.crs.to_epsg() != 3857:
        link_gdf_proj = link_gdf.to_crs('EPSG:3857')
        print("[INFO] 已将路网投影到 EPSG:3857，单位为米")

    sindex = link_gdf_proj.sindex
    use_graph = (G is not None) and (gamma > 0)

    for idx in abnormal_indices:
        row = df_corrected.loc[idx]
        agent_id = row['agent_id']
        seq = row['seq']
        orig_point = gpd.GeoSeries([Point(row['lng'], row['lat'])], crs='EPSG:4326').to_crs('EPSG:3857').iloc[0]
        orig_dist = row['distance']
        current_osm_id = row['osm_segment_id']

        if debug:
            print(f"\n=== 异常点 idx={idx}, agent={agent_id}, seq={seq} ===")
            print(f"原始GPS: ({row['lng']:.6f}, {row['lat']:.6f})")
            print(f"当前匹配: osm_id={current_osm_id}, dist={orig_dist:.2f}m")

        # ---------- 获取前后各 context_points 个点 ----------
        group = df_corrected[df_corrected['agent_id'] == agent_id].sort_values('seq')
        prev_rows = []
        next_rows = []
        for i in range(1, context_points + 1):
            if seq - i >= 0:
                prev_rows.append(group[group['seq'] == seq - i].iloc[0])
        for i in range(1, context_points + 1):
            if seq + i <= group['seq'].max():
                next_rows.append(group[group['seq'] == seq + i].iloc[0])

        # 获取前后点对应的路段
        prev_links = []
        for pr in prev_rows:
            link_id = pr['osm_segment_id']
            lk = link_gdf[link_gdf['osm_id'] == link_id]
            if not lk.empty:
                prev_links.append(lk.iloc[0])
        next_links = []
        for nr in next_rows:
            link_id = nr['osm_segment_id']
            lk = link_gdf[link_gdf['osm_id'] == link_id]
            if not lk.empty:
                next_links.append(lk.iloc[0])

        if debug:
            print(f"前 {len(prev_links)} 个路段, 后 {len(next_links)} 个路段")

        # ---------- 计算上下文方向 ----------
        context_angle = None
        if prev_rows and next_rows:
            lon1 = prev_rows[0]['lng']; lat1 = prev_rows[0]['lat']
            lon2 = next_rows[0]['lng']; lat2 = next_rows[0]['lat']
            if abs(lon2 - lon1) > 1e-8 or abs(lat2 - lat1) > 1e-8:
                context_angle = np.degrees(np.arctan2(lat2 - lat1, lon2 - lon1)) % 360
        elif prev_rows and len(prev_rows) >= 2:
            lon1 = prev_rows[1]['lng']; lat1 = prev_rows[1]['lat']
            lon2 = prev_rows[0]['lng']; lat2 = prev_rows[0]['lat']
            context_angle = np.degrees(np.arctan2(lat2 - lat1, lon2 - lon1)) % 360
        elif next_rows and len(next_rows) >= 2:
            lon1 = next_rows[0]['lng']; lat1 = next_rows[0]['lat']
            lon2 = next_rows[1]['lng']; lat2 = next_rows[1]['lat']
            context_angle = np.degrees(np.arctan2(lat2 - lat1, lon2 - lon1)) % 360
        else:
            if has_bearing and pd.notna(row['bearing']):
                context_angle = row['bearing']

        if debug and context_angle is not None:
            print(f"上下文方向: {context_angle:.1f}°")

        # ---------- 工具函数：计算路段的评分 ----------
        def compute_link_score(link_row, orig_point, bearing_angle, context_angle):
            dist = link_row.geometry.distance(orig_point)
            score_dist = np.exp(-dist / 10.0)

            # 方向分
            score_heading = 0.0
            coords = list(link_row.geometry.coords)
            if len(coords) >= 2:
                dx = coords[-1][0] - coords[0][0]
                dy = coords[-1][1] - coords[0][1]
                road_angle = np.degrees(np.arctan2(dy, dx)) % 360

                if bearing_angle is not None:
                    angle_diff = abs(road_angle - bearing_angle) % 360
                    if angle_diff > 180:
                        angle_diff = 360 - angle_diff
                    score_bearing = (np.cos(np.radians(angle_diff)) + 1.0) / 2.0
                else:
                    score_bearing = 0.0

                if context_angle is not None:
                    ctx_diff = abs(road_angle - context_angle) % 360
                    if ctx_diff > 180:
                        ctx_diff = 360 - ctx_diff
                    score_context = (np.cos(np.radians(ctx_diff)) + 1.0) / 2.0
                else:
                    score_context = 0.0

                if bearing_angle is not None and context_angle is not None:
                    score_heading = (score_bearing + score_context) / 2
                elif bearing_angle is not None:
                    score_heading = score_bearing
                elif context_angle is not None:
                    score_heading = score_context

            # 连通性分
            connect_scores = []
            for prev_link in prev_links:
                prev_to = int(prev_link['to_node'])
                link_from = int(link_row['from_node'])
                try:
                    if nx.has_path(G, prev_to, link_from):
                        path_len = nx.shortest_path_length(G, prev_to, link_from, weight='weight')
                        connect_scores.append(np.exp(-path_len / 2000))
                    else:
                        connect_scores.append(1.0 if prev_to == link_from else 0.0)
                except:
                    if prev_to == link_from:
                        connect_scores.append(0.8)
                    else:
                        connect_scores.append(0.0)
            for next_link in next_links:
                link_to = int(link_row['to_node'])
                next_from = int(next_link['from_node'])
                try:
                    if nx.has_path(G, link_to, next_from):
                        path_len = nx.shortest_path_length(G, link_to, next_from, weight='weight')
                        connect_scores.append(np.exp(-path_len / 2000))
                    else:
                        connect_scores.append(1.0 if link_to == next_from else 0.0)
                except:
                    if link_to == next_from:
                        connect_scores.append(0.8)
                    else:
                        connect_scores.append(0.0)
            score_connect = np.mean(connect_scores) if connect_scores else 0.0

            total = alpha * score_dist + beta * score_heading + gamma * score_connect
            return total, score_dist, score_heading, score_connect

        # ---------- 获取当前匹配路段的评分 ----------
        current_link = link_gdf_proj[link_gdf_proj['osm_id'] == current_osm_id]
        if not current_link.empty:
            current_link = current_link.iloc[0]
            bearing_angle = row['bearing'] if has_bearing and pd.notna(row['bearing']) else None
            current_score, _, _, _ = compute_link_score(
                current_link, orig_point, bearing_angle, context_angle
            )
            if debug:
                print(f"当前匹配评分: {current_score:.3f}")
        else:
            current_score = -1.0

        # ---------- 搜索候选路段 ----------
        bbox = orig_point.buffer(buffer_radius).bounds
        possible = list(sindex.intersection(bbox))
        if not possible:
            continue
        candidates = link_gdf_proj.iloc[possible]
        candidates = candidates[candidates.geometry.distance(orig_point) <= buffer_radius]
        if candidates.empty:
            continue

        if len(candidates) > max_candidates:
            candidates['_dist'] = candidates.geometry.distance(orig_point)
            candidates = candidates.nsmallest(max_candidates, '_dist')

        best_score = -1
        best_link = None
        best_proj_point = None

        max_allowed_dist = max(orig_dist * max_dist_factor, 15)

        for _, link in candidates.iterrows():
            dist = link.geometry.distance(orig_point)
            if dist > max_allowed_dist:
                if debug:
                    print(f"候选 osm_id={link['osm_id']} 距离 {dist:.2f}m 超过阈值 {max_allowed_dist:.2f}m，跳过")
                continue

            total_score, score_dist, score_heading, score_connect = compute_link_score(
                link, orig_point, bearing_angle, context_angle
            )

            if debug:
                print(f"候选 osm_id={link['osm_id']}, dist={dist:.2f}, "
                      f"scores: dist={score_dist:.3f}, head={score_heading:.3f}, conn={score_connect:.3f}, total={total_score:.3f}")

            if total_score > best_score:
                best_score = total_score
                best_link = link
                best_proj_point = nearest_points(link.geometry, orig_point)[0]

        # ---------- 决定是否修正 ----------
        if best_link is not None:
            improvement = best_score - current_score
            if improvement <= 0:
                if debug:
                    print(f"[WARN] 最佳候选评分 {best_score:.3f} 不优于当前匹配 {current_score:.3f}，保留原匹配")
                continue
            if keep_threshold > 0 and improvement < keep_threshold:
                if debug:
                    print(f"[WARN] 候选仅提升 {improvement:.3f}，低于阈值 {keep_threshold:.3f}，保留原匹配")
                continue

            new_dist = orig_point.distance(best_proj_point)

            projected_new_point = gpd.GeoSeries([best_proj_point], crs='EPSG:3857').to_crs('EPSG:4326').iloc[0]
            df_corrected.loc[idx, 'osm_segment_id'] = best_link['osm_id']
            df_corrected.loc[idx, 'matched_lon'] = projected_new_point.x
            df_corrected.loc[idx, 'matched_lat'] = projected_new_point.y
            df_corrected.loc[idx, 'distance'] = new_dist
            if debug:
                print(f"[OK] 修正: osm_id {current_osm_id} -> {best_link['osm_id']}, 距离 {orig_dist:.2f} -> {new_dist:.2f}m")
        else:
            if debug:
                print("[WARN] 未找到有效候选，保持原样")

    return df_corrected

# ===================================================
# 3. 主程序
# ===================================================
if __name__ == "__main__":
    # ---------- 文件路径（请修改为您的实际路径） ----------
    FULL_MATCH_CSV = r"D:\xiangmu\other\data\1\2\traj_108229327582031908_all.csv"
    SUSPICIOUS_CSV = r"D:\xiangmu\other\data\1\2\traj_108229327582031908_suspicious.csv"
    LINK_GPKG = r"D:\xiangmu\other\input\road\link.gpkg"
    NODE_GPKG = r"D:\xiangmu\other\input\road\node.gpkg"  # 可选
    OUTPUT_DIR = r"D:\xiangmu\other\data\1\jieguo"

    # ---------- 1. 加载完整匹配结果 ----------
    print("加载完整匹配结果...")
    df_match = pd.read_csv(FULL_MATCH_CSV, sep=';', encoding='utf-8-sig')
    df_match.columns = df_match.columns.str.strip().str.replace('\ufeff', '')
    print("完整匹配结果列名:", df_match.columns.tolist())

    # 自动识别点ID列（优先 orig_point_id / origin_point_id）
    id_candidates = ['orig_point_id', 'origin_point_id', 'point_id']
    id_col = None
    for col in id_candidates:
        if col in df_match.columns:
            id_col = col
            break
    if id_col is None:
        raise ValueError(f"完整匹配结果缺少点ID列，现有列名: {df_match.columns.tolist()}")
    if id_col != 'orig_point_id':
        df_match.rename(columns={id_col: 'orig_point_id'}, inplace=True)

    # 重命名匹配坐标列
    if 'match_lon' in df_match.columns:
        df_match.rename(columns={'match_lon': 'matched_lon', 'match_lat': 'matched_lat'}, inplace=True)

    # 检查必要列（现在 seq 来自 point_order）
    required_cols = ['orig_point_id', 'agent_id', 'point_order', 'lng', 'lat',
                     'matched_lon', 'matched_lat', 'osm_segment_id', 'distance']
    for col in required_cols:
        if col not in df_match.columns:
            raise ValueError(f"完整匹配结果缺少列: {col}")

    # 将 point_order 重命名为 seq
    df_match.rename(columns={'point_order': 'seq'}, inplace=True)
    # 确保按 agent_id 和 seq 排序
    df_match = df_match.sort_values(['agent_id', 'seq']).reset_index(drop=True)

    # 将 orig_point_id 转为字符串
    df_match['orig_point_id'] = df_match['orig_point_id'].astype(str)

    # ---------- 2. 加载异常点列表 ----------
    print("加载异常点列表...")
    df_suspicious = pd.read_csv(SUSPICIOUS_CSV, sep=';', encoding='utf-8-sig')
    df_suspicious.columns = df_suspicious.columns.str.strip().str.replace('\ufeff', '')
    print("异常点列表列名:", df_suspicious.columns.tolist())

    # 自动识别异常点中的点ID列
    id_col_sus = None
    for col in id_candidates:
        if col in df_suspicious.columns:
            id_col_sus = col
            break
    if id_col_sus is None:
        raise ValueError(f"异常点列表缺少点ID列，现有列名: {df_suspicious.columns.tolist()}")
    if id_col_sus != 'orig_point_id':
        df_suspicious.rename(columns={id_col_sus: 'orig_point_id'}, inplace=True)

    # 处理顺序列：优先 point_idx，其次 point_index
    if 'point_idx' in df_suspicious.columns:
        seq_col = 'point_idx'
    elif 'point_index' in df_suspicious.columns:
        seq_col = 'point_index'
    else:
        raise ValueError("异常点列表缺少 point_idx 或 point_index 列")
    # 重命名为 seq
    df_suspicious.rename(columns={seq_col: 'seq'}, inplace=True)

    # 确保 seq 为整数，并处理起始值（若从 1 开始则减 1，否则保持不变）
    df_suspicious['seq'] = df_suspicious['seq'].astype(int)
    min_seq = df_suspicious['seq'].min()
    if min_seq == 1:
        df_suspicious['seq'] = df_suspicious['seq'] - 1
    print(f"异常点 seq 范围: {df_suspicious['seq'].min()} ~ {df_suspicious['seq'].max()}")

    df_suspicious['orig_point_id'] = df_suspicious['orig_point_id'].astype(str)
    print(f"异常点数量: {len(df_suspicious)}")

    # ---------- 3. 定位异常点 ----------
    print("定位异常点...")
    # 使用 (agent_id, seq) 组合键定位
    df_match['key'] = df_match['agent_id'].astype(str) + "_" + df_match['seq'].astype(str)
    df_suspicious['key'] = df_suspicious['agent_id'].astype(str) + "_" + df_suspicious['seq'].astype(str)

    key_to_idx = {k: idx for idx, k in enumerate(df_match['key'])}
    abnormal_indices = []
    missing_keys = []

    for _, row in df_suspicious.iterrows():
        key = row['key']
        if key in key_to_idx:
            abnormal_indices.append(key_to_idx[key])
        else:
            missing_keys.append(key)

    print(f"成功匹配异常点: {len(abnormal_indices)}")
    if missing_keys:
        print(f"[WARN] 未找到的 key 数量: {len(missing_keys)}，已忽略")
        # 可将缺失的 key 保存到文件以便检查
        with open(os.path.join(OUTPUT_DIR, "missing_keys.txt"), 'w') as f:
            for k in missing_keys:
                f.write(k + "\n")

    if not abnormal_indices:
        print("[INFO] 没有可修正的点，程序退出。")
        exit(0)

    # ---------- 4. 计算 bearing ----------
    if 'bearing' not in df_match.columns:
        print("未检测到 bearing，根据 GPS 点计算...")
        df_match = add_bearing_from_gps(df_match)

    # ---------- 5. 加载路网 ----------
    print("加载路网...")
    link = gpd.read_file(LINK_GPKG)
    if link.crs is None or link.crs.to_epsg() != 4326:
        link = link.to_crs('EPSG:4326')

    if 'osm_id' not in link.columns:
        raise ValueError("路网缺少 osm_id 列")
    if 'from_node' not in link.columns or 'to_node' not in link.columns:
        raise ValueError("路网缺少 from_node 或 to_node 列")
    if 'length' not in link.columns:
        raise ValueError("路网缺少 length 列")

    link['from_node'] = link['from_node'].astype(int)
    link['to_node'] = link['to_node'].astype(int)
    print(f"路段数: {len(link)}")

    # ---------- 6. 构建路网图 ----------
    print("构建路网图...")
    G = nx.Graph()
    for _, row in link.iterrows():
        G.add_edge(row['from_node'], row['to_node'], weight=row['length'])
    print(f"图节点数: {G.number_of_nodes()}, 边数: {G.number_of_edges()}")

    # ---------- 7. 执行修正 ----------
    print("执行修正...")
    df_corrected = correct_abnormal_points(
        df_matched=df_match,
        link_gdf=link,
        node_gdf=None,
        G=G,
        abnormal_indices=abnormal_indices,
        buffer_radius=40,
        alpha=0.05,
        beta=0.85,
        gamma=0.10,
        max_candidates=20,
        use_heading=True,
        debug=True,                # 调试模式
        max_dist_factor=1.5,
        context_points=3,
        keep_threshold=0.0
    )

    # ---------- 8. 保存结果 ----------
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out_full = os.path.join(OUTPUT_DIR, "match_result_corrected.csv")
    df_corrected.to_csv(out_full, sep=';', index=False)
    print(f"[OK] 修正后的完整结果已保存: {out_full}")

    report = df_corrected.loc[abnormal_indices, [
        'point_id', 'osm_segment_id', 'matched_lon', 'matched_lat', 'distance'
    ]].copy()
    original = df_match.loc[abnormal_indices, [
        'osm_segment_id', 'matched_lon', 'matched_lat', 'distance'
    ]].copy()
    report.columns = ['point_id', 'new_osm_id', 'new_lon', 'new_lat', 'new_dist']
    original.columns = ['old_osm_id', 'old_lon', 'old_lat', 'old_dist']
    report = pd.concat([report, original], axis=1)
    report['agent_id'] = df_corrected.loc[abnormal_indices, 'agent_id'].values

    out_report = os.path.join(OUTPUT_DIR, "modification_report.csv")
    report.to_csv(out_report, sep=';', index=False)
    print(f"[OK] 修正报告已保存: {out_report}")

    print("\n[OK] 全部处理完成！")