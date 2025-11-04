import os
import pandas as pd


class EvaluationResult:
    def __init__(self, propose_set_count: int, mean_validation_time: float = None):
        self.propose_set_count = propose_set_count
        self.mean_validation_time = mean_validation_time


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


def evaluate_log(log_dir):
    # 如果存在 log_dir/iteration-1/action-1.csv，则进行评估
    action_log_path = f"{log_dir}/iteration-1/action-1.csv"
    if not os.path.exists(action_log_path):
        print(f"Action log file {action_log_path} does not exist.")
        return
    df_action = pd.read_csv(action_log_path)
    # 计算 "message_type"为"TMProposeSet" 的行数
    propose_set_count = get_prop_set_count(df_action)

    df_result = pd.read_csv(f"{log_dir}/iteration-1/result-1.csv")
    mean_validation_time = get_avg_validation_time(df_result)
    if mean_validation_time is not None:
        print(f"Average validation time: {mean_validation_time} seconds")

    return EvaluationResult(
        propose_set_count=propose_set_count, mean_validation_time=mean_validation_time
    )


if __name__ == "__main__":
    evaluate_log("/home/luanli/rocket/logs/2025_11_04_16h47m/G1")
