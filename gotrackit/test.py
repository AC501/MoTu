import pandas as pd
import numpy as np

input_csv = r"D:\xiangmu\motu\data\1\full_match_result_all.csv"   # 请修改为您的实际文件路径
output_csv = r"D:\xiangmu\motu\data\1\match_result_40000.csv"

# 指定分隔符为分号
df = pd.read_csv(input_csv, sep=';')

# 打印列名确认
print("列名：", df.columns.tolist())

# 获取所有唯一的 agent_id
all_agents = df['agent_id'].unique()
print(f"总轨迹数：{len(all_agents)}")

# 随机保留 40000 条轨迹
np.random.seed(42)   # 可选，保证结果可重复
keep_agents = np.random.choice(all_agents, size=35000, replace=False)
print(f"保留轨迹数：{len(keep_agents)}")

# 筛选数据
df_filtered = df[df['agent_id'].isin(keep_agents)]

# 保存（仍以分号分隔，保持原格式）
df_filtered.to_csv(output_csv, sep=';', index=False)
print(f"筛选后行数：{len(df_filtered)}，已保存至 {output_csv}")