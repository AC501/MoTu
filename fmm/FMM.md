**1.从 PostgreSQL 导出所有轨迹点**

COPY (

&#x20;   SELECT 

&#x20;       ROW\_NUMBER() OVER (ORDER BY t.traj\_id, t.locate\_time) AS id,   -- 全局连续ID

&#x20;       t.traj\_id AS orig\_traj\_id,                                     -- 原始轨迹ID

&#x20;       t.point\_id AS orig\_point\_id,                                   -- 原始点ID（point\_id）

&#x20;       t.longitude AS x,

&#x20;       t.latitude AS y,

&#x20;       EXTRACT(EPOCH FROM t.locate\_time) AS timestamp

&#x20;   FROM (

&#x20;       SELECT DISTINCT ON (traj\_id, latitude, longitude, locate\_time)

&#x20;           traj\_id,

&#x20;           point\_id,              -- 原始点ID字段

&#x20;           longitude,

&#x20;           latitude,

&#x20;           locate\_time

&#x20;       FROM trajectory\_point\_raw

&#x20;       ORDER BY traj\_id, locate\_time

&#x20;   ) t

&#x20;   ORDER BY t.traj\_id, t.locate\_time

) TO 'D:/Desktop/motu/traj\_all\_continuous\_raw.csv' 

WITH (FORMAT CSV, HEADER true, DELIMITER ';');

**2.坐标转换**

在 Cygwin 中执行以下命令，创建并运行转换脚本 convert\_to\_wgs84\_all.py：

cd /cygdrive/d/Desktop/motu



cat > convert\_to\_wgs84\_all.py <<'EOF'

import csv, math



\# ============================================================

\# 函数：gcj02\_to\_wgs84

\# 功能：将GCJ-02（火星坐标系）经纬度转换为WGS-84经纬度

\# 参数：lon - 火星坐标系经度，lat - 火星坐标系纬度

\# 返回：转换后的WGS-84经纬度元组 (wgs\_lon, wgs\_lat)

\# 说明：GCJ-02是中国国家测绘局制定的坐标偏移系统，用于GPS数据脱敏

\#       本函数使用经典迭代逼近算法进行逆向纠偏

\# ============================================================

def gcj02\_to\_wgs84(lon, lat):

&#x20;   # 常数定义：π、椭球体长半轴、第一偏心率平方

&#x20;   pi = 3.1415926535897932384626

&#x20;   a = 6378245.0              # 克拉索夫斯基椭球体长半轴（米）

&#x20;   ee = 0.00669342162296594323  # 第一偏心率平方



&#x20;   # 辅助函数：计算纬度偏移量（用于纠偏）

&#x20;   def transform\_lat(lon, lat):

&#x20;       ret = -100.0 + 2.0 \* lon + 3.0 \* lat + 0.2 \* lat \* lat + 0.1 \* lon \* lat + 0.2 \* math.sqrt(abs(lon))

&#x20;       ret += (20.0 \* math.sin(6.0 \* lon \* pi) + 20.0 \* math.sin(2.0 \* lon \* pi)) \* 2.0 / 3.0

&#x20;       ret += (20.0 \* math.sin(lat \* pi) + 40.0 \* math.sin(lat / 3.0 \* pi)) \* 2.0 / 3.0

&#x20;       ret += (160.0 \* math.sin(lat / 12.0 \* pi) + 320 \* math.sin(lat \* pi / 30.0)) \* 2.0 / 3.0

&#x20;       return ret



&#x20;   # 辅助函数：计算经度偏移量（用于纠偏）

&#x20;   def transform\_lon(lon, lat):

&#x20;       ret = 300.0 + lon + 2.0 \* lat + 0.1 \* lon \* lon + 0.1 \* lon \* lat + 0.1 \* math.sqrt(abs(lon))

&#x20;       ret += (20.0 \* math.sin(6.0 \* lon \* pi) + 20.0 \* math.sin(2.0 \* lon \* pi)) \* 2.0 / 3.0

&#x20;       ret += (20.0 \* math.sin(lon \* pi) + 40.0 \* math.sin(lon / 3.0 \* pi)) \* 2.0 / 3.0

&#x20;       ret += (150.0 \* math.sin(lon / 12.0 \* pi) + 300.0 \* math.sin(lon / 30.0 \* pi)) \* 2.0 / 3.0

&#x20;       return ret



&#x20;   # 计算当前点相对于中国基准点的偏移量（中国区域近似值）

&#x20;   dlon = transform\_lon(lon - 105.0, lat - 35.0)

&#x20;   dlat = transform\_lat(lon - 105.0, lat - 35.0)



&#x20;   # 将角度转换为弧度，计算椭球体相关参数

&#x20;   radlat = lat / 180.0 \* pi

&#x20;   magic = math.sin(radlat)

&#x20;   magic = 1 - ee \* magic \* magic

&#x20;   sqrtmagic = math.sqrt(magic)



&#x20;   # 将偏移量从“度”转换为实际经纬度增量

&#x20;   dlon = (dlon \* 180.0) / (a / sqrtmagic \* math.cos(radlat) \* pi)

&#x20;   dlat = (dlat \* 180.0) / ((a \* (1 - ee)) / (magic \* sqrtmagic) \* pi)



&#x20;   # 返回纠偏后的WGS-84坐标（火星坐标减去偏移量）

&#x20;   return lon - dlon, lat - dlat





\# ============================================================

\# 主程序：读取原始CSV文件，转换坐标，输出新CSV

\# ============================================================

with open('traj\_all\_continuous\_raw.csv', 'r') as f\_in, \\

&#x20;    open('traj\_all\_continuous\_ready.csv', 'w') as f\_out:



&#x20;   # 使用分号作为分隔符的CSV读写器

&#x20;   reader = csv.reader(f\_in, delimiter=';')

&#x20;   writer = csv.writer(f\_out, delimiter=';')



&#x20;   # 读取表头，并写入新文件（列顺序保持不变）

&#x20;   header = next(reader)

&#x20;   # 新表头列：id, orig\_traj\_id, orig\_point\_id, x, y, timestamp

&#x20;   writer.writerow(\['id', 'orig\_traj\_id', 'orig\_point\_id', 'x', 'y', 'timestamp'])



&#x20;   # 逐行处理数据

&#x20;   for row in reader:

&#x20;       # 跳过字段不足的行（安全保护）

&#x20;       if len(row) < 6:

&#x20;           continue



&#x20;       try:

&#x20;           # 提取字段并去除首尾空格

&#x20;           new\_id = row\[0].strip()

&#x20;           orig\_traj\_id = row\[1].strip()

&#x20;           orig\_point\_id = row\[2].strip()

&#x20;           lon = float(row\[3].strip())   # 原始经度（GCJ-02）

&#x20;           lat = float(row\[4].strip())   # 原始纬度（GCJ-02）

&#x20;           ts = row\[5].strip()

&#x20;       except ValueError:

&#x20;           # 若转换失败（非数字），跳过该行

&#x20;           continue



&#x20;       # 调用转换函数，得到WGS-84坐标

&#x20;       wgs\_lon, wgs\_lat = gcj02\_to\_wgs84(lon, lat)



&#x20;       # 写入转换后的数据（保持其他字段不变）

&#x20;       writer.writerow(\[new\_id, orig\_traj\_id, orig\_point\_id, wgs\_lon, wgs\_lat, ts])



\# 输出完成提示

print("坐标转换完成，生成 traj\_all\_continuous\_ready.csv")

EOF



python convert\_to\_wgs84\_all.py



**3.运行 FMM 匹配**

cd /cygdrive/d/Desktop/motu



\# ============================================================

\# FMM 地图匹配命令（逐点匹配模式）

\# 功能：将GPS轨迹点独立匹配到OSM路网上，输出匹配结果

\# 输入：traj\_all\_continuous\_ready.csv（分号分隔，列：id, orig\_traj\_id, orig\_point\_id, x, y, timestamp）

\# 输出：result\_all.txt（分号分隔，包含匹配路段ID、匹配坐标、偏差等）

\# ============================================================



/cygdrive/d/fmm-master/build/fmm \\

&#x20; # ---------- 路网预处理数据 ----------

&#x20; --ubodt ubodt.txt \\ # ubodt: 预计算的最短路径表，用于加速路径搜索

&#x20; # ---------- 路网数据 ----------

&#x20; --network road\_fixed.shp \\

&#x20; # road\_fixed.shp: OSM路网Shapefile，包含道路几何和属性

&#x20; # ---------- GPS输入文件 ----------

&#x20; --gps traj\_all\_continuous\_ready.csv \\  # 输入文件：分号分隔的CSV，必须包含 id, x, y, timestamp 列

&#x20;  # ---------- 输出文件 ----------

&#x20; --output result\_all.txt \\# 匹配结果文件，分号分隔，包含所有输出字段（由 --output\_fields 控制）

&#x20; # ---------- 匹配模式 ----------

&#x20; --gps\_point \\  # 在该模式下，FMM仅计算点到路段的观测概率  --gps\_id id \\

&#x20; # 指定输入文件中轨迹/点ID的列名（此处为全局唯一连续ID）

&#x20; --gps\_x x \\  # 指定经度列名

&#x20; --gps\_y y \\  # 指定纬度列名

&#x20;--gps\_timestamp timestamp \\

&#x20;   -k 20 \\

&#x20; -r 0.05 \\

&#x20;  -e 0.005 \\

&#x20;   --use\_omp \\

&#x20; --output\_fields all

&#x20;

**4.解析结果并生成最终匹配表**

cat > parse\_result\_all.py <<'EOF'

import csv, re

from math import radians, sin, cos, sqrt, atan2



def haversine(lon1, lat1, lon2, lat2):

&#x20;   R = 6371000

&#x20;   phi1, phi2 = radians(lat1), radians(lat2)

&#x20;   dphi = radians(lat2 - lat1)

&#x20;   dlambda = radians(lon2 - lon1)

&#x20;   a = sin(dphi/2)\*\*2 + cos(phi1)\*cos(phi2)\*sin(dlambda/2)\*\*2

&#x20;   c = 2 \* atan2(sqrt(a), sqrt(1-a))

&#x20;   return R \* c



def distance\_range(dist):

&#x20;   if dist < 0:

&#x20;       return "无效"

&#x20;   elif dist < 5:

&#x20;       return "0-5m"

&#x20;   elif dist < 10:

&#x20;       return "5-10m"

&#x20;   elif dist < 20:

&#x20;       return "10-20m"

&#x20;   elif dist < 30:

&#x20;       return "20-30m"

&#x20;   elif dist < 50:

&#x20;       return "30-50m"

&#x20;   else:

&#x20;       return "≥50m"



print("读取原始点信息...")

point\_info = {}

with open('traj\_all\_continuous\_ready.csv', 'r') as f:

&#x20;   reader = csv.reader(f, delimiter=';')

&#x20;   header = next(reader)

&#x20;   for row in reader:

&#x20;       if len(row) < 6:

&#x20;           continue

&#x20;       pid = int(row\[0])

&#x20;       orig\_traj\_id = row\[1]

&#x20;       orig\_point\_id = row\[2]

&#x20;       lon = float(row\[3]); lat = float(row\[4]); ts = row\[5]

&#x20;       point\_info\[pid] = {

&#x20;           'orig\_traj\_id': orig\_traj\_id,

&#x20;           'orig\_point\_id': orig\_point\_id,

&#x20;           'lon': lon,

&#x20;           'lat': lat,

&#x20;           'timestamp': ts

&#x20;       }

print(f"读取了 {len(point\_info)} 个点")



print("解析 FMM 结果...")

records = \[]

with open('result\_all.txt', 'r') as f\_in:

&#x20;   header\_line = f\_in.readline().strip().split(';')

&#x20;   col\_idx = {col: i for i, col in enumerate(header\_line)}

&#x20;   traj\_id\_col = col\_idx.get('traj\_id', 0)

&#x20;   cpath\_col = col\_idx.get('cpath', 6)

&#x20;   mgeom\_col = col\_idx.get('mgeom', 8)



&#x20;   for line in f\_in:

&#x20;       parts = line.strip().split(';')

&#x20;       if len(parts) <= max(traj\_id\_col, cpath\_col, mgeom\_col):

&#x20;           continue

&#x20;       traj\_id = int(parts\[traj\_id\_col])

&#x20;       cpath = parts\[cpath\_col]

&#x20;       mgeom = parts\[mgeom\_col]

&#x20;       if not mgeom or mgeom == 'NULL':

&#x20;           continue

&#x20;       coords = re.findall(r'(\[0-9.]+)\\s+(\[0-9.]+)', mgeom)

&#x20;       edge\_ids = \[int(x) for x in cpath.split(',') if x.strip()] if cpath else \[]

&#x20;       if not coords:

&#x20;           continue



&#x20;       info = point\_info.get(traj\_id)

&#x20;       if not info:

&#x20;           continue

&#x20;       orig\_lon = info\['lon']; orig\_lat = info\['lat']

&#x20;       orig\_traj\_id = info\['orig\_traj\_id']

&#x20;       orig\_point\_id = info\['orig\_point\_id']

&#x20;       timestamp = info\['timestamp']



&#x20;       for i, (lon\_str, lat\_str) in enumerate(coords):

&#x20;           matched\_lon = float(lon\_str); matched\_lat = float(lat\_str)

&#x20;           dist = haversine(orig\_lon, orig\_lat, matched\_lon, matched\_lat)

&#x20;           osm\_id = edge\_ids\[i] if i < len(edge\_ids) else -1

&#x20;           confidence = 1.0 / (1.0 + dist / 10)

&#x20;           records.append({

&#x20;               'point\_id': traj\_id,                # 全局连续ID

&#x20;               'orig\_point\_id': orig\_point\_id,      # 原始点ID

&#x20;               'agent\_id': orig\_traj\_id,

&#x20;               'osm\_segment\_id': osm\_id,

&#x20;               'lng': orig\_lon,

&#x20;               'lat': orig\_lat,

&#x20;               'matched\_lon': matched\_lon,

&#x20;               'matched\_lat': matched\_lat,

&#x20;               'distance': dist,

&#x20;               'confidence': confidence,

&#x20;               'match\_time': timestamp,

&#x20;               'distance\_range': distance\_range(dist)

&#x20;           })



print(f"共解析出 {len(records)} 条记录，正在排序...")

\# 按 agent\_id 和 point\_id 排序

records\_sorted = sorted(records, key=lambda r: (r\['agent\_id'], r\['point\_id']))



print("输出最终结果表...")

with open('full\_match\_result\_all.csv', 'w', newline='') as f:

&#x20;   writer = csv.writer(f, delimiter=';')

&#x20;   writer.writerow(\['match\_id','point\_id','orig\_point\_id','agent\_id','osm\_segment\_id',

&#x20;                    'lng','lat','matched\_lon','matched\_lat',

&#x20;                    'distance','confidence','match\_time','distance\_range'])

&#x20;   for idx, rec in enumerate(records\_sorted, start=1):

&#x20;       writer.writerow(\[

&#x20;           idx,

&#x20;           rec\['point\_id'],

&#x20;           rec\['orig\_point\_id'],

&#x20;           rec\['agent\_id'],

&#x20;           rec\['osm\_segment\_id'],

&#x20;           rec\['lng'],

&#x20;           rec\['lat'],

&#x20;           rec\['matched\_lon'],

&#x20;           rec\['matched\_lat'],

&#x20;           rec\['distance'],

&#x20;           rec\['confidence'],

&#x20;           rec\['match\_time'],

&#x20;           rec\['distance\_range']

&#x20;       ])



print(f"结果表已生成: full\_match\_result\_all.csv，共 {len(records\_sorted)} 条记录")

EOF



python parse\_result\_all.py





