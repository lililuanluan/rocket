

import os
import pandas as pd

class EvaluationResult:
    def __init__(self, propose_set_count: int):
        self.propose_set_count = propose_set_count

def get_prop_set_count(df: pd.DataFrame) -> int:
    return df[df["message_type"] == "TMProposeSet"].shape[0]

def evaluate_log(log_dir):
    # 如果存在 log_dir/iteration-1/action-1.csv，则进行评估
    action_log_path = f"{log_dir}/iteration-1/action-1.csv"
    if not os.path.exists(action_log_path):
        print(f"Action log file {action_log_path} does not exist.")
        return
    df = pd.read_csv(action_log_path)
    # 计算 "message_type"为"TMProposeSet" 的行数
    propose_set_count = get_prop_set_count(df)

    return EvaluationResult(propose_set_count=propose_set_count)



if __name__ == "__main__":
    evaluate_log("/home/luanli/rocket/logs/2025_11_04_16h47m/G1")