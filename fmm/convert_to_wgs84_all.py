import csv, math

def gcj02_to_wgs84(lon, lat):
    pi = 3.1415926535897932384626
    a = 6378245.0
    ee = 0.00669342162296594323
    def transform_lat(lon, lat):
        ret = -100.0 + 2.0 * lon + 3.0 * lat + 0.2 * lat * lat + 0.1 * lon * lat + 0.2 * math.sqrt(abs(lon))
        ret += (20.0 * math.sin(6.0 * lon * pi) + 20.0 * math.sin(2.0 * lon * pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(lat * pi) + 40.0 * math.sin(lat / 3.0 * pi)) * 2.0 / 3.0
        ret += (160.0 * math.sin(lat / 12.0 * pi) + 320 * math.sin(lat * pi / 30.0)) * 2.0 / 3.0
        return ret
    def transform_lon(lon, lat):
        ret = 300.0 + lon + 2.0 * lat + 0.1 * lon * lon + 0.1 * lon * lat + 0.1 * math.sqrt(abs(lon))
        ret += (20.0 * math.sin(6.0 * lon * pi) + 20.0 * math.sin(2.0 * lon * pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(lon * pi) + 40.0 * math.sin(lon / 3.0 * pi)) * 2.0 / 3.0
        ret += (150.0 * math.sin(lon / 12.0 * pi) + 300.0 * math.sin(lon / 30.0 * pi)) * 2.0 / 3.0
        return ret
    dlon = transform_lon(lon - 105.0, lat - 35.0)
    dlat = transform_lat(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlon = (dlon * 180.0) / (a / sqrtmagic * math.cos(radlat) * pi)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * pi)
    return lon - dlon, lat - dlat

with open('traj_all_continuous_raw.csv', 'r') as f_in, \
     open('traj_all_continuous_ready.csv', 'w') as f_out:
    reader = csv.reader(f_in, delimiter=';')
    writer = csv.writer(f_out, delimiter=';')
    header = next(reader)
    writer.writerow(['id', 'orig_traj_id', 'orig_point_id', 'x', 'y', 'timestamp'])
    for row in reader:
        if len(row) < 6:
            continue
        try:
            new_id = row[0].strip()
            orig_traj_id = row[1].strip()
            orig_point_id = row[2].strip()
            lon = float(row[3].strip())
            lat = float(row[4].strip())
            ts = row[5].strip()
        except ValueError:
            continue
        wgs_lon, wgs_lat = gcj02_to_wgs84(lon, lat)
        writer.writerow([new_id, orig_traj_id, orig_point_id, wgs_lon, wgs_lat, ts])
print("✅ 坐标转换完成，生成 traj_all_continuous_ready.csv")
