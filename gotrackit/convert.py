import csv
import math


# ---------------- 坐标转换核心函数 (无需改动) ----------------
def out_of_china(lng, lat):
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)


def transform_lat(x, y):
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def transform_lng(x, y):
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def gcj02_to_wgs84(lng, lat):
    if out_of_china(lng, lat):
        return lng, lat
    a = 6378245.0
    ee = 0.00669342162296594323
    dlat = transform_lat(lng - 105.0, lat - 35.0)
    dlng = transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrt_magic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrt_magic) * math.pi)
    dlng = (dlng * 180.0) / (a / sqrt_magic * math.cos(radlat) * math.pi)
    mg_lat = lat + dlat
    mg_lng = lng + dlng
    return lng * 2 - mg_lng, lat * 2 - mg_lat


# ---------------- 处理主逻辑 ----------------
def convert_csv(input_path, output_path):
    # 使用 utf-8-sig 可以自动跳过 Excel 导出的 BOM 头，避免列名匹配出错
    with open(input_path, newline='', encoding='utf-8-sig') as fin, \
            open(output_path, 'w', newline='', encoding='utf-8-sig') as fout:

        reader = csv.DictReader(fin)
        fieldnames = reader.fieldnames
        print(f"✅ 读取到表头: {fieldnames}")  # 帮你打印，确保能看到列名

        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()

        count = 0
        for row in reader:
            count += 1
            try:
                lng = float(row['lng'])
                lat = float(row['lat'])
            except Exception as e:
                print(f"⚠️ 第 {count} 行数据异常跳过: {e} -> {row}")
                writer.writerow(row)
                continue

            wgs_lng, wgs_lat = gcj02_to_wgs84(lng, lat)
            row['lng'] = f'{wgs_lng:.12f}'
            row['lat'] = f'{wgs_lat:.12f}'
            writer.writerow(row)

        print(f"🎉 处理完成！共处理 {count} 行数据。输出文件已保存至: {output_path}")


# ---------------- 直接在这里运行 (不再需要终端输路径) ----------------
if __name__ == '__main__':
    # ↓↓↓ 在这里修改你的文件路径 ↓↓↓
    # r"" 表示原始字符串，Windows路径里带反斜杠 \ 不会被转义，建议保留 r
    input_csv = r"D:\xiangmu\motu\gotrackit\input\08.csv"
    output_csv = r"D:\xiangmu\motu\gotrackit\input\08_convert.csv"

    print("🚀 开始执行坐标转换程序...")
    convert_csv(input_csv, output_csv)