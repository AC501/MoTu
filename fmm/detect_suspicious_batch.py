import csv
import math
from collections import defaultdict, Counter

# ============================================================
# 1. 加载映射表
# ============================================================
print("加载映射表...")
id_map = {}
with open('id_mapping_traj.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter=';')
    for row in reader:
        id_map[row['short_id']] = row['original_agent']
print(f"加载了 {len(id_map)} 条映射")

# ============================================================
# 2. 加载轨迹匹配结果
# ============================================================
print("加载 traj_match_result.txt ...")
fmm_data = {}
with open('traj_match_result.txt', 'r', encoding='utf-8') as f:
    lines = f.readlines()
    if len(lines) < 2:
        print("错误：traj_match_result.txt 为空")
        exit()
    header = lines[0].strip().split(';')

    idx_id = header.index('id')
    idx_cpath = header.index('cpath')
    idx_spdist = header.index('spdist')
    idx_error = header.index('error')
    idx_offset = header.index('offset')
    idx_ep = header.index('ep')
    idx_tp = header.index('tp')

    def parse_seq(s):
        if not s:
            return []
        vals = []
        for x in s.split(','):
            x = x.strip()
            if not x:
                continue
            if x.lower() == 'inf':
                vals.append(float('inf'))
            else:
                try:
                    vals.append(float(x))
                except ValueError:
                    vals.append(None)
        return vals

    for line in lines[1:]:
        parts = line.strip().split(';')
        if len(parts) <= max(idx_id, idx_cpath, idx_spdist):
            continue
        short_id = parts[idx_id]
        original_agent = id_map.get(short_id)
        if not original_agent:
            continue
        fmm_data[original_agent] = {
            'cpath': parse_seq(parts[idx_cpath]),
            'spdist': parse_seq(parts[idx_spdist]),
            'error': parse_seq(parts[idx_error]),
            'offset': parse_seq(parts[idx_offset]),
            'ep': parse_seq(parts[idx_ep]),
            'tp': parse_seq(parts[idx_tp]),
        }
print(f"加载了 {len(fmm_data)} 条轨迹的 FMM 参数")

# ============================================================
# 3. 加载点匹配结果
# ============================================================
print("加载 all_distance_leq5_trajectories.csv ...")
trajs = defaultdict(list)
with open('all_distance_leq5_trajectories.csv', 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter=';')
    for row in reader:
        trajs[row['agent_id']].append(row)
print(f"共 {len(trajs)} 条轨迹")

# ============================================================
# 4. 辅助函数
# ============================================================
def haversine(lon1, lat1, lon2, lat2):
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

def bearing(lon1, lat1, lon2, lat2):
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    if abs(dlon) < 1e-10 and abs(dlat) < 1e-10:
        return 0
    ang = math.degrees(math.atan2(dlon, dlat))
    return ang if ang >= 0 else ang + 360

def angle_diff(a, b):
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d

# ============================================================
# 5. 逐轨迹检测
# ============================================================
suspicious = []
print("开始检测可疑点...")

for agent, rows in trajs.items():
    rows.sort(key=lambda x: int(x.get('point_order', 0)))
    n = len(rows)
    if n < 3:
        continue

    # 提取点数据
    lons = [float(r['lng']) for r in rows]
    lats = [float(r['lat']) for r in rows]
    times = [float(r['match_time']) for r in rows]
    roads = [r['osm_segment_id'] for r in rows]
    dists = [float(r['distance']) for r in rows]
    confs = [float(r['confidence']) if r['confidence'] else 0.0 for r in rows]
    orig_ids = [r['orig_point_id'] for r in rows]
    matched_lons = [float(r['matched_lon']) for r in rows]
    matched_lats = [float(r['matched_lat']) for r in rows]
    point_orders = [int(r.get('point_order', i+1)) for i, r in enumerate(rows)]

    # 获取 FMM 参数
    fmm = fmm_data.get(agent, {})
    spdist = fmm.get('spdist', [])
    error = fmm.get('error', [])
    offset = fmm.get('offset', [])
    ep = fmm.get('ep', [])
    tp = fmm.get('tp', [])
    cpath = fmm.get('cpath', [])

    for i in range(1, n-1):
        rid = roads[i]
        if rid == '-1' or rid == '':
            continue
        rid = int(rid)
        reasons = []

        # ----- 1. spdist 异常 -----
        if i < len(spdist):
            spd = spdist[i]
            if spd == float('inf'):
                reasons.append("路网不连通(spdist=inf)")
            elif i > 0:
                gps_dist = haversine(lons[i-1], lats[i-1], lons[i], lats[i])
                if gps_dist > 10 and spd > gps_dist * 3:
                    reasons.append(f"最短路径异常(spdist={spd:.0f}m)")

        # ----- 2. offset 越界 -----
        if i < len(offset) and offset[i] is not None:
            if offset[i] < 0 or offset[i] > 1:
                reasons.append(f"offset越界({offset[i]:.3f})")

        # ----- 3. error 过大 -----
        if i < len(error) and error[i] is not None:
            if error[i] > 50:
                reasons.append(f"匹配误差大({error[i]:.1f}m)")

        # ----- 4. 低观测概率 / 传递概率 -----
        if i < len(ep) and ep[i] is not None and ep[i] < 0.3:
            reasons.append(f"低观测概率({ep[i]:.2f})")
        if i < len(tp) and tp[i] is not None and tp[i] < 0.3:
            reasons.append(f"低传递概率({tp[i]:.2f})")

        # ----- 5. cpath 与点匹配不一致 -----
        if i < len(cpath):
            if int(cpath[i]) != rid:
                reasons.append(f"路段不一致(轨迹匹配{int(cpath[i])} vs 点匹配{rid})")

        # ----- 6. 方向反向 -----
        gps_b = bearing(lons[i-1], lats[i-1], lons[i+1], lats[i+1])
        match_b = bearing(matched_lons[i-1], matched_lats[i-1], matched_lons[i+1], matched_lats[i+1])
        if angle_diff(gps_b, match_b) > 130:
            reasons.append("行驶方向反向")

        # ----- 7. 震荡切换 -----
        if i >= 2 and i < n-1:
            if (roads[i-1] == roads[i+1] and roads[i-1] != '-1' and roads[i-1] != roads[i]):
                dt1 = times[i] - times[i-1]
                dt2 = times[i+1] - times[i]
                if dt1 < 20 and dt2 < 20:
                    reasons.append("道路震荡切换")

        # ----- 8. 速度异常 -----
        dt = times[i] - times[i-1]
        if dt > 0:
            spd = (haversine(lons[i-1], lats[i-1], lons[i], lats[i]) / dt) * 3.6
            if spd > 110:
                reasons.append(f"速度异常({spd:.0f}km/h)")

        # ----- 9. 低置信度 -----
        if confs[i] < 0.4:
            reasons.append("低置信度")

        # ----- 10. 距离突变 -----
        if i > 0 and i < n-1:
            if dists[i] > dists[i-1] * 3 and dists[i] > dists[i+1] * 3 and dists[i] > 5:
                reasons.append("匹配距离突变")

        # ----- 11. 几何跳变 -----
        if i < n-1:
            gps_d = haversine(lons[i], lats[i], lons[i+1], lats[i+1])
            match_d = haversine(matched_lons[i], matched_lats[i], matched_lons[i+1], matched_lats[i+1])
            if gps_d > 10 and match_d > gps_d * 2.5:
                reasons.append("几何跳变(绕路)")

        if reasons:
            suspicious.append({
                'agent_id': agent,
                'orig_point_id': orig_ids[i],
                'point_idx': point_orders[i],
                'match_road_id': rid,
                'suspicion_reason': '; '.join(reasons),
                'spdist': spdist[i] if i < len(spdist) else None,
                'error': error[i] if i < len(error) else None,
                'offset': offset[i] if i < len(offset) else None,
                'ep': ep[i] if i < len(ep) else None,
                'tp': tp[i] if i < len(tp) else None,
            })

print(f"共发现 {len(suspicious)} 个可疑点")

# ============================================================
# 6. 输出
# ============================================================
output_file = 'suspicious_from_traj_match.csv'
with open(output_file, 'w', newline='', encoding='utf-8') as f:
    fieldnames = ['agent_id', 'orig_point_id', 'point_idx', 'match_road_id',
                  'suspicion_reason', 'spdist', 'error', 'offset', 'ep', 'tp']
    writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';')
    writer.writeheader()
    writer.writerows(suspicious)

print(f"✅ 输出文件: {output_file}")

cnt = Counter()
for item in suspicious:
    for r in item['suspicion_reason'].split('; '):
        if r.strip():
            cnt[r.strip()] += 1
print("\n可疑原因分布：")
for r, c in cnt.most_common():
    print(f"  {r}: {c}")
