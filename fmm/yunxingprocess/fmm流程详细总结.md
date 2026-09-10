# FMM 轨迹匹配完整流程总结

## 1. 流程概览

本流程以高德路网和 GPS 轨迹为输入，经过路网拓扑整理、轨迹抽样与清洗、FMM（Fast Map Matching）匹配，最后将匹配结果与原始 GPS 点叠加绘图。

完整顺序如下：

1. 在 QGIS 中使用 `v.clean` 对高德路网进行几何清理和打断，得到可用于后续建网的路网数据。
2. 使用 `handle02.py` 读取 `v.clean` 的结果：
   - 统一为 WGS84 坐标系；
   - 清理无效几何、拆分多部件线；
   - 按端点容差合并节点；
   - 为每条道路生成正向和反向边；
   - 输出 FMM 所需的 `nodes.shp` 和 `edges.shp`。
3. 使用 `clean_100.py` 处理原始轨迹：
   - 随机抽取轨迹；
   - 将轨迹 WKT 拆成带时间戳的点；
   - 过滤速度异常点；
   - 使用 Douglas-Peucker 方法抽稀；
   - 重新生成带时间戳的轨迹 WKT；
   - 输出 FMM 输入文件。
4. 在 Cygwin 或其他 FMM 运行环境中，使用处理后的轨迹文件和 `handle02.py` 生成的路网进行 FMM 匹配。脚本明确要求使用 `--gps_id id`，即以轨迹文件中的 `id` 字段作为 GPS 轨迹标识。
5. 使用 `chakantupian.py` 读取 FMM 生成的结果文件，将 `mgeom` 匹配线、未抽稀的原始 GPS 点和高德路网底图绘制到单条轨迹图片中。

其中，前三个 Python 脚本分别负责路网建网、轨迹预处理和结果可视化；FMM 的实际匹配命令不包含在这三个脚本中。

---

## 2. 路网处理：`handle02.py`

脚本路径：`d:\xiangmu\motu\fmm\pre_handle\handle02.py`（根据自己目录实际调整）

### 2.1 输入和输出

默认输入：

```text
D:\xiangmu\other\gaode\gd1\gd1.shp
```

该文件应是 QGIS `v.clean` 处理后的高德路网。脚本默认输出到：

```text
D:\xiangmu\other\gaode\gd1_fix
```

输出文件：

```text
nodes.shp
edges.shp
```

其中：

- `nodes.shp`：路网节点，包含 `id`、`x`、`y` 和点几何；
- `edges.shp`：路网边，包含 `id`、`source`、`target` 和线几何；
- 两个文件均使用 `EPSG:4326`；
- 输出格式为 ESRI Shapefile。

### 2.2 坐标系处理

脚本读取路网后检查 CRS：

- 如果输入没有 CRS，则设置为 `EPSG:4326`；
- 如果输入 CRS 不是 WGS84，则转换为 `EPSG:4326`；
- 如果已经是 WGS84，则直接使用。

因此，后续轨迹数据和 FMM 路网应保持经纬度坐标体系一致。

### 2.3 几何清理

脚本会保留非空且有效的线几何，并执行以下处理：

1. 删除空几何和空值几何；
2. 只保留 `LineString` 和 `MultiLineString`；
3. 使用 `explode` 将多部件线拆成独立的单线段；
4. 删除长度小于 `1e-8` 的极短线段。

QGIS `v.clean` 负责前置的路网几何清理和打断，`handle02.py` 则负责将清理后的线段进一步转换为 FMM 拓扑网络。

### 2.4 节点合并与容差

脚本默认节点合并容差为：

```python
TOL = 1e-5
```

输入数据是经纬度时，该值约等于 1 米量级。节点生成逻辑如下：

1. 读取每条线的首坐标和尾坐标；
2. 将坐标除以容差并四舍五入，得到桶索引；
3. 先在当前桶中查找已有节点；
4. 再检查周围 8 个邻域桶；
5. 如果已有节点与当前坐标在容差范围内，则复用该节点；
6. 否则创建新的节点 ID。

这种桶式空间索引可以减少全量节点两两比较，适合较大范围路网处理。

### 2.5 双向边生成

每条有效道路线会生成两条边：

- 正向边：起点为 `source`，终点为 `target`，保留原始坐标顺序；
- 反向边：起点和终点互换，同时反转线坐标顺序。

因此，输出网络默认将所有道路设置为双向。边的 `id` 从 1 开始连续递增，节点的 `id` 也从 1 开始。

需要注意：脚本没有读取或保留原始道路的方向属性、限行属性或道路等级属性。经过该脚本生成的网络在拓扑层面统一按双向道路处理。

---

## 3. 轨迹预处理：`clean_100.py`

脚本路径：`d:\xiangmu\other\input\clean_100.py`

### 3.1 输入和输出

默认原始轨迹文件：

```text
D:\xiangmu\other\input\10-20\traj_input_10-20.csv
```

脚本使用分号 `;` 读取输入，至少依赖以下字段：

- `id`：原始轨迹 ID；
- `geometry`：轨迹 WKT，通常为 `LineString`；
- `timestamp`：与轨迹坐标对应的时间戳字符串，多个时间戳使用逗号分隔。

输出目录默认为：

```text
cleaned_output_5
```

主要输出文件：

```text
sampled_original.csv
points_for_cleaning.csv
cleaned_trajectories_wkt.csv
```

### 3.2 随机抽样

脚本参数为：

```python
SAMPLE_SIZE = 300
```

当输入轨迹数不少于 300 条时，使用：

```python
sample(n=SAMPLE_SIZE, random_state=42)
```

进行固定随机种子的抽样，因此在输入数据不变时可以复现抽样结果。当输入轨迹数少于 300 条时，使用全部轨迹。

抽样后：

- 重置 DataFrame 索引；
- 增加从 1 开始的 `short_id`；
- 将抽样结果原样保存到 `sampled_original.csv`。

`sampled_original.csv` 后续还会被可视化脚本读取，用于恢复未抽稀的原始 GPS 点。

### 3.3 WKT 拆点

脚本读取每条轨迹的 `geometry`，将线几何拆解为坐标点，并将轨迹的 `timestamp` 字符串按逗号拆分。

坐标和时间戳按位置一一对应，实际写入数量取两者长度的较小值，生成字段：

```text
traj_id;lng;lat;timestamp
```

输出文件为 `points_for_cleaning.csv`，仍使用分号分隔。

### 3.4 时间转换和速度异常过滤

拆点数据的时间戳按 Unix 秒解析为日期时间，并构造 WGS84 点图层：

```python
crs="EPSG:4326"
```

随后使用 MovingPandas 的 `OutlierCleaner`，按照最大速度 120 km/h 进行过滤：

```python
cleaned = mpd.OutlierCleaner(traj_collection).clean(
    v_max=120,
    units=("km", "h")
)
```

速度过滤后，仅保留点数不少于 3 个的轨迹。若没有任何轨迹通过过滤，脚本直接退出。

### 3.5 Douglas-Peucker 抽稀

抽稀参数为：

```python
TOLERANCE_METERS = 5
MIN_POINTS_RATIO = 0.1
```

由于轨迹坐标是经纬度，5 米容差会转换为近似角度：

```python
tolerance_deg = TOLERANCE_METERS / 111320
```

处理逻辑如下：

1. 点数少于 5 个的轨迹不抽稀；
2. 将轨迹点构造成 `LineString`；
3. 调用 Shapely 的 `simplify` 进行 Douglas-Peucker 抽稀；
4. 对抽稀后的每个新坐标，使用 KDTree 在原始点中查找最近邻；
5. 将最近邻原始点的时间戳赋给新坐标；
6. 如果抽稀后点数小于 `max(5, 原始点数 * 0.1)`，则放弃本次抽稀并保留原轨迹。

该步骤的目的不是简单删除固定比例的点，而是在保留轨迹形状的同时减少冗余点，并防止轨迹被抽稀得过度。

### 3.6 清洗后 WKT 导出

所有保留轨迹会重新汇总为点数据，并生成：

- `traj_id`
- `lng`
- `lat`
- `timestamp`

之后按 `traj_id` 分组重新构造 `LineString`，并将时间戳转换回 Unix 秒，以逗号连接。

最终输出字段为：

```text
id;short_id;geometry;timestamp
```

输出文件为：

```text
cleaned_output_5/cleaned_trajectories_wkt.csv
```

脚本最后明确提示：FMM 匹配时使用 `--gps_id id`，即使用输出文件中的 `id` 作为轨迹标识。通常这里的 `id` 是原始轨迹的长 ID，`short_id` 主要用于抽样记录和人工识别。

---

## 4. FMM 匹配阶段

FMM 命令本身未出现在提供的三个脚本中，但从脚本之间的文件约定可以确定其输入输出关系。

### 4.1 FMM 输入

FMM 应使用：

1. `clean_100.py` 生成的 `cleaned_trajectories_wkt.csv`；
2. `handle02.py` 生成的 `nodes.shp`；
3. `handle02.py` 生成的 `edges.shp`。

轨迹文件中的：

- `id` 用作 GPS 轨迹 ID；
- `geometry` 用作待匹配轨迹；
- `timestamp` 保存轨迹点时间；
- `short_id` 是辅助映射字段，不应替代脚本提示中的 `id`。
FMM 命令示例：
匹配命令
fmm   --network /cygdrive/d/xiangmu/other/gaode/gd1_fix/edges.shp   --network_id id   --source source   --target target   --ubodt ubodt_chengdugd_0.02.txt   --gps cleaned_output_5/cleaned_trajectories_wkt.csv   --output result_suiji303.txt   --gps_id id   --gps_geom geometry   --gps_timestamp timestamp   -k 12 -r 0.0007 -e 0.0005   --use_omp   --output_fields all


ubodt生成命令
ubodt_gen \
  --network "./chengdu_road_network2/edges.shp" \
  --output ubodt_chengdu_0.02.txt \
  --delta 0.02 \
  --network_id fid \
  --source u \
  --target v



### 4.2 FMM 输出

可视化脚本将 FMM 结果读取为表格，并使用其中的：

- `id`：匹配轨迹 ID；
- `mgeom`：匹配后的几何线。

实际结果文件名和路径由 `chakantupian.py` 配置，目前默认是：

```text
D:\xiangmu\other\input\cleaned_output_5\result_01.txt
```

脚本不会重新执行匹配，而是直接读取已经生成的结果文件。因此，FMM 输出中的 ID 必须能够与清洗后输入文件中的 `id` 对应。

---

## 5. 结果可视化：`chakantupian.py`

脚本路径：`d:\xiangmu\other\input\chakantupian.py`

### 5.1 默认文件配置

脚本默认读取：

```text
cleaned_trajectories_wkt.csv  # 清洗后的轨迹，用于 ID 映射
sampled_original.csv          # 抽样后的原始轨迹，用于恢复未抽稀点
result_01.txt                 # FMM 匹配结果
gd.shp                        # 高德路网底图
```

图片输出到：

```text
D:\xiangmu\other\input\trajectory_plots02
```

输出目录不存在时会自动创建。

### 5.2 读取和 ID 映射

清洗后的轨迹和 FMM 结果使用自动分隔符识别方式读取；FMM 结果的字段按字符串读取。

FMM 结果中的 `id` 会先转换为数值并升序排序，保证图片按轨迹 ID 顺序生成。

对于每条匹配结果：

1. 在清洗后的输入文件中查找相同的 `id`；
2. 从匹配记录中取得原始 `traj_id`；
3. 在 `sampled_original.csv` 中用该原始 ID 查找完整的原始轨迹；
4. 将原始轨迹的所有坐标拆成点；
5. 将 FMM 结果的 `mgeom` 解析为匹配线。

因此，可视化使用的是：

- 红色虚线：FMM 匹配后的 `mgeom`；
- 蓝色点：抽样后但未抽稀的原始 GPS 点；
- 灰色线：局部高德路网底图。

这与 FMM 实际使用的清洗后、抽稀后的轨迹不同，目的是更直观地检查匹配结果与原始采样点之间的关系。

### 5.3 WKT 解析和坐标系

WKT 几何使用 Shapely 解析，并统一构造为：

```text
EPSG:4326
```

高德路网底图读取后，如果 CRS 与轨迹点不一致，则转换为轨迹点的 CRS。

如果路网加载失败，脚本会输出警告并继续绘图，此时图片中不显示灰色路网底图，但仍可能绘制原始点和匹配线。

### 5.4 单条轨迹绘图

每条轨迹单独生成一张 `10 x 10` 英寸的图片。绘图范围由原始点和匹配线的总边界共同决定，并在横纵方向各增加 10% 边距；如果某个方向没有范围，则使用 `0.001` 的默认边距。

绘图层次为：

1. 局部高德路网：浅灰色、较细线宽；
2. 原始 GPS 点：蓝色点；
3. FMM 匹配线：红色粗虚线。

图片标题包含：

```text
Trajectory <FMM轨迹ID> (原始ID: <原始轨迹ID>)
```

坐标轴被隐藏，图片以 150 DPI 保存，文件名为：

```text
traj_<FMM轨迹ID>.png
```

### 5.5 处理结果

脚本只要找到对应的清洗轨迹或匹配线，就会尝试生成图片；如果两者都为空则跳过该轨迹。每处理 5 条轨迹打印一次进度，最终打印实际生成图片的数量和输出目录。

---

## 6. 文件与字段衔接关系

| 阶段 | 主要输入 | 主要输出 | 关键字段 |
|---|---|---|---|
| QGIS `v.clean` | 原始高德路网 | 清理、打断后的路网 | 线几何 |
| `handle02.py` | `gd1.shp` | `nodes.shp`、`edges.shp` | 节点 `id`、边 `source`/`target` |
| `clean_100.py` 抽样 | 原始轨迹 CSV | `sampled_original.csv` | 原始 `id`、`short_id` |
| `clean_100.py` 拆点 | 抽样轨迹 WKT | `points_for_cleaning.csv` | `traj_id`、坐标、时间 |
| `clean_100.py` 清洗 | 拆点轨迹 | `cleaned_trajectories_wkt.csv` | `id`、`short_id`、`geometry`、`timestamp` |
| FMM | 清洗轨迹、节点、边 | `result_01.txt` 等结果文件 | `id`、`mgeom` |
| `chakantupian.py` | 清洗轨迹、原始抽样轨迹、FMM 结果、底图 | 每条轨迹一张 PNG | 轨迹 ID、匹配几何 |

---

## 7. 关键参数汇总

| 参数 | 所属脚本 | 默认值 | 作用 |
|---|---|---:|---|
| `TOL` | `handle02.py` | `1e-5` | 路网端点合并容差，单位为经纬度 |
| `epsg` | `handle02.py` | `4326` | 路网目标坐标系 |
| `SAMPLE_SIZE` | `clean_100.py` | `300` | 随机抽取的轨迹条数 |
| `random_state` | `clean_100.py` | `42` | 固定抽样结果 |
| `TOLERANCE_METERS` | `clean_100.py` | `5` | 轨迹抽稀容差，单位为米 |
| `MIN_POINTS_RATIO` | `clean_100.py` | `0.1` | 抽稀后最少点数比例 |
| `v_max` | `clean_100.py` | `120 km/h` | 速度异常过滤阈值 |
| 边距比例 | `chakantupian.py` | `10%` | 图片边界留白 |
| DPI | `chakantupian.py` | `150` | 图片输出分辨率 |

---

## 8. 复现和检查注意事项

1. **先处理路网，再进行 FMM。** `nodes.shp` 和 `edges.shp` 应由已经经过 QGIS `v.clean` 的路网生成。
2. **路网和轨迹都使用 WGS84。** 路网脚本和轨迹预处理脚本均以 `EPSG:4326` 为基础。
3. **确认分隔符。** `clean_100.py` 明确使用分号输出；可视化脚本使用自动分隔符识别，但其他 FMM 工具仍应确认实际分隔符要求。
4. **保持 `id` 一致。** FMM 使用 `--gps_id id`，结果文件中的 `id` 必须能够在 `cleaned_trajectories_wkt.csv` 中找到。
5. **区分 `id`、`short_id` 和 `traj_id`。**
   - `id`：FMM 交互使用的轨迹标识；
   - `short_id`：抽样后生成的辅助短编号；
   - `traj_id`：清洗过程中用于分组和回溯原始轨迹的 ID。
6. **可视化使用未抽稀点。** FMM 使用清洗、过滤和抽稀后的轨迹，而图片中的蓝色点来自 `sampled_original.csv` 的完整坐标，因此两者点数可能不同。
7. **时间戳必须与坐标顺序一致。** WKT 坐标和逗号分隔的时间戳按位置匹配，长度不一致时只保留较短的一方。
8. **检查路网打断质量。** `handle02.py` 只根据每条线的首尾点建边；如果 QGIS `v.clean` 没有正确打断交叉或连接道路，可能导致网络拓扑不连通。
9. **注意双向化假设。** 所有输入线都会生成正向和反向边，脚本不会根据道路属性判断单行道。
10. **检查输出目录和文件命名。** 可视化脚本依赖具体路径和文件名，换批次运行时应同步修改配置区。
11. **关注异常轨迹。** 速度过滤后少于 3 个点的轨迹会被删除；抽稀后点数过少时会恢复原轨迹；没有有效 WKT 的记录会被跳过。
12. **确认 FMM 输出字段。** 可视化至少需要结果文件中的 `id` 和 `mgeom` 字段。

---

## 9. 一句话总结

该流程先将 QGIS `v.clean` 处理后的高德路网转换成具有节点、正反向边和 WGS84 几何的 FMM 路网，再对轨迹进行固定种子抽样、速度异常过滤和 Douglas-Peucker 抽稀，使用清洗结果进行 FMM 匹配，最后将匹配生成的 `mgeom` 与未抽稀的原始 GPS 点及路网底图叠加，按轨迹输出可视化图片。
