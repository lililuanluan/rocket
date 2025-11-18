import os
import pandas as pd





def get_prop_set_count(df: pd.DataFrame) -> int:
    return df[df["message_type"] == "TMProposeSet"].shape[0]


def get_avg_validation_time(df: pd.DataFrame) -> float:

    # 筛选 ledger_seq > 2 的行
    df_filtered = df[df["ledger_seq"] > 2]

    # 获取这些行的验证时间（去除空值）
    validation_times = df_filtered["time_to_validation"].dropna()

    if validation_times.empty:
        print("No validation times found.")
        return None

    return validation_times.mean()

def get_test_total_time(f):
    if isinstance(f, pd.DataFrame):
        df = f
    else:
        df = pd.read_csv(f)
    
    df = df["timestamp"]
    if df.empty:
        print("No timestamps found.")
        return None
    return (df.max() - df.min()) / 1000.0
    


def evaluate_log(log_dir):
    # 如果存在 log_dir/iteration-1/action-1.csv，则进行评估
    action_log_path = f"{log_dir}/iteration-1/action-1.csv"
    if not os.path.exists(action_log_path):
        print(f"Action log file {action_log_path} does not exist.")
        return None
    df_action = pd.read_csv(action_log_path)
    # 计算 "message_type"为"TMProposeSet" 的行数
    propose_set_count = get_prop_set_count(df_action)

    result_log_path = f"{log_dir}/iteration-1/result-1.csv"
    if not os.path.exists(result_log_path):
        print(f"Result log file {result_log_path} does not exist.")
        return None
    df_result = pd.read_csv(result_log_path)
    mean_validation_time = get_avg_validation_time(df_result)

    # 读取 aggregated_spec_check_log.json（注意：这是一个对象，不是数组）
    aggregate_spec_check_path = f"{log_dir}/aggregated_spec_check_log.json"
    if not os.path.exists(aggregate_spec_check_path):
        print(f"Aggregated spec check log file {aggregate_spec_check_path} does not exist.")
        return None
    import json
    with open(aggregate_spec_check_path, "r") as f:
        agg_spec_check = json.load(f)

    # 直接从字典中提取失败计数
    total_failures = agg_spec_check.get("failed_termination", 0) + agg_spec_check.get("failed_agreement", 0)
    correct_runs = agg_spec_check.get("correct_runs", 0)
    failed_final_agreement = agg_spec_check.get("failed_final_agreement", 0)
    failed_agreement = agg_spec_check.get("failed_agreement", 0)
    
    test_duration = get_test_total_time(df_action)

    return {
        "test_duration": test_duration,
        "propose_set_count": propose_set_count,
        "mean_validation_time": mean_validation_time,
        "total_failures": total_failures,
        "correct_runs": correct_runs,
        "failed_final_agreement": failed_final_agreement,
        "failed_agreement": failed_agreement,
        "agg_spec_check": agg_spec_check,
    }




if __name__ == "__main__":
    evaluate_log("/home/luanli/rocket/logs/2025_11_04_16h47m/G1")
