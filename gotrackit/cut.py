import pandas as pd

# ===================== 配置 =====================
input_csv = r"D:\xiangmu\motu\data\full_match_result_all.csv"   # 请修改为您的实际文件路径
output_dir = r"D:\xiangmu\motu\data"                    # 输出目录

# ===================== 读取数据 =====================
df = pd.read_csv(input_csv, sep=';')

# 确保 distance 列为数值类型，非数值转为 NaN
df['distance'] = pd.to_numeric(df['distance'], errors='coerce')

# 查看是否有无效值
nan_count = df['distance'].isna().sum()
if nan_count > 0:
    print(f"警告：发现 {nan_count} 行 distance 无效（NaN），将单独统计为 '无效'。")

# ===================== 区间划分 =====================
bins = [0, 5, 10, 20, 30, 50, float('inf')]
labels = ['0-5m', '5-10m', '10-20m', '20-30m', '30-50m', '≥50m']

# 左闭右开区间 [0,5), [5,10), ...
df['distance_range'] = pd.cut(
    df['distance'],
    bins=bins,
    labels=labels,
    right=False
)

# 单独标记无效值（NaN）为 '无效'
df['distance_range'] = df['distance_range'].cat.add_categories(['无效']).fillna('无效')

# ===================== 统计 =====================
# 计算每个区间的点数（包括无效）
counts = df['distance_range'].value_counts()
total = len(df)                     # 总点数
percentages = (counts / total * 100).round(2)

# 整理成 DataFrame，并按区间顺序排序
stat_df = pd.DataFrame({
    '区间': counts.index,
    '点数': counts.values,
    '占比(%)': percentages.values
})

# 确保区间顺序与定义的 labels 一致（但无效值排在最后）
ordered_labels = labels + ['无效']
stat_df['区间'] = pd.Categorical(stat_df['区间'], categories=ordered_labels, ordered=True)
stat_df = stat_df.sort_values('区间').reset_index(drop=True)

# ========== 新增：添加总计行 ==========
total_row = pd.DataFrame({
    '区间': ['总计'],
    '点数': [total],
    '占比(%)': [100.0]
})
stat_df = pd.concat([stat_df, total_row], ignore_index=True)

# ===================== 保存统计 CSV =====================
stat_csv = f"{output_dir}\\distance_statistics.csv"
stat_df.to_csv(stat_csv, index=False, encoding='utf_8_sig')
print(f"\n统计结果已保存至：{stat_csv}")

# ===================== 控制台打印 =====================
print("\n各区间匹配点数量及占比（含总计）：")
print(stat_df.to_string(index=False))

# ===================== 可选：将带有区间列的完整数据保存 =====================
full_csv = f"{output_dir}\\match_result_with_range.csv"
df.to_csv(full_csv, index=False)
print(f"\n已保存带区间列的完整数据至：{full_csv}")

# ===================== 按区间拆分 CSV（按需） =====================
for label in labels + ['无效']:
    subset = df[df['distance_range'] == label]
    if not subset.empty:
        safe_label = label.replace('≥', 'ge').replace('m', '')
        file_name = f"match_result_{safe_label}.csv"
        subset.to_csv(f"{output_dir}\\{file_name}", index=False)
        print(f"已保存区间 {label} 的数据，共 {len(subset)} 行，文件：{file_name}")

print("\n全部处理完成！")