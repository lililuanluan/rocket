import pandas as pd
import hashlib


def hash_action_log(log_dir):
    # 读取csv文件
    df = pd.read_csv(log_dir)
    # 将每一行按照 timestamp 排序
    df_sorted = df.sort_values(by="timestamp")
    trace  = []
    # 将每一行提取出一个三元组：<from_node_id, to_node_id, message_type>
    for index, row in df_sorted.iterrows():
        trace.append((row["from_node_id"], row["to_node_id"], row["message_type"]))
    # 将所有三元组拼接成一个字符串
    trace_str = ''.join([f"{t[0]}-{t[1]}-{t[2]}\n" for t in trace])
    # 计算字符串的hash值
    hash_value = hashlib.sha256(trace_str.encode()).hexdigest()
    print(trace_str)
    print(f"Action log hash: {hash_value}")

if __name__ == "__main__":
    hash_action_log("../logs/mylog/iteration-1/action-1.csv")