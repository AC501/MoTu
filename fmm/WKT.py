import csv#将轨迹转换为WKT格式输入
from collections import defaultdict

input_file = 'worst_dist_5_10_trajectories.csv'
output_file = 'worst_dist_5_10_trajectories_wkt.csv'

print("读取点数据...")
groups = defaultdict(list)
with open(input_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f, delimiter=';')
    for row in reader:
        agent = row['agent_id']
        groups[agent].append({
            'order': int(row['point_order']),
            'lng': float(row['lng']),
            'lat': float(row['lat']),
            'time': row['match_time']
        })

print(f"共 {len(groups)} 条轨迹")

print("生成 WKT...")
with open(output_file, 'w', encoding='utf-8') as f:
    writer = csv.writer(f, delimiter=';')
    writer.writerow(['id', 'geometry', 'timestamp'])
    for agent, points in groups.items():
        points.sort(key=lambda x: x['order'])
        coords = []
        times = []
        for p in points:
            coords.append(f"{p['lng']} {p['lat']}")
            times.append(p['time'])
        geometry = f"LINESTRING ({', '.join(coords)})"
        timestamp_seq = ','.join(times)
        writer.writerow([agent, geometry, timestamp_seq])

print(f"✅ 转换完成，生成 {output_file}")
EOF
