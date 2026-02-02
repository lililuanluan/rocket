import sys
import os
import pandas as pd
import numpy as np
import json
import re
import codecs
from typing import Tuple, Set

# Ensure project root is on sys.path so local packages like 'protos' can be imported

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
# Retry import; if it still fails, let the exception propagate so the caller can see the underlying issue
from protos.packet_pb2 import Packet as ProtoPacket
from rocket_controller.encoder_decoder import PacketEncoderDecoder, DecodingNotSupportedError

def get_prop_set_count(df: pd.DataFrame) -> int:
    return df[df["message_type"] == "TMProposeSet"].shape[0]


def get_getledger_stats(df_exec) -> Tuple[Set[str], int]:
    requested_ledger_hashes = set()  # ledgerHash (hex string)
    total_requests = 0
    for _, row in df_exec.iterrows():
        if row["message_type"] != "TMGetLedger":
            continue
        total_requests += 1
        # Prefer using the raw packet bytes logged in the 'packet_data' column
        packet_hex = row.get("packet_data")
        if not packet_hex or pd.isna(packet_hex):
            # If packet_data is missing, skip this row (avoid string parsing)
            continue

        try:
            packet_bytes = bytes.fromhex(packet_hex)
            packet = ProtoPacket(data=packet_bytes)
            message, msg_type = PacketEncoderDecoder.decode_packet(packet)

            # TMGetLedger.ledgerHash is a bytes field; convert to hex for readability
            ledger_bytes = getattr(message, "ledgerHash", None)
            if ledger_bytes:
                requested_ledger_hashes.add(ledger_bytes.hex())
        except (ValueError, DecodingNotSupportedError, Exception):
            # decoding failed for this row; ignore and continue
            continue

    return requested_ledger_hashes, total_requests


def get_validation_times(df: pd.DataFrame, node_info: dict) -> dict:
    # 以相对的 ledger_index 确定起始点：从 min(ledger_index)+1 开始
    if "ledger_index" not in df.columns:
        print("ledger_index column not found in dataframe.")
        return None

    try:
        min_idx = int(df["ledger_index"].min())
    except Exception:
        print("Could not determine min ledger_index.")
        return None

    start_idx = min_idx + 1
    df_filtered = df[df["ledger_index"] >= start_idx]

    validation_times = {}
    # 返回 node_id: {ledger_index: validation_time}}
    for node_id, (private_key, public_key) in node_info.items():
        node_validations = df_filtered[df_filtered["node_id"] == node_id]
        validation_times[node_id] = dict(
            zip(
                node_validations["ledger_index"], node_validations["time_to_validation"]
            )
        )

    return validation_times


def get_avg_validation_time(validation_times: dict) -> float:

    if not validation_times:
        print("No validation times found after start index.")
        return None

    all_times = [time for times in validation_times.values() for time in times.values()]
    return sum(all_times) / len(all_times)


def get_validation_time_var(vt: dict) -> float:
    vars = []
    seq = set()
    for r in vt.values():
        seq.update(r.keys())
    for s in seq:
        times = []
        for node_id, r in vt.items():
            if s in r:
                times.append(r[s])
        if len(times) > 1:
            var = np.var(times)
            vars.append(var)

    # 返回vars的平均值
    return np.mean(vars) if vars else None


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


def get_node_info(log_dir):
    node_info_path = f"{log_dir}/iteration-1/node_info-1.csv"
    if not os.path.exists(node_info_path):
        print(f"Node info file {node_info_path} does not exist.")
        return None
    df_node_info = pd.read_csv(node_info_path)
    # 返回 {node_id: (private_key, public_key)}
    return {
        row["node_id"]: (row["private_key"], row["public_key"])
        for _, row in df_node_info.iterrows()
    }


def evaluate_log(log_dir, byzz_nodes: list = None):

    node_info = get_node_info(log_dir)
    # print(f"Node info: {node_info}")

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
    validation_times = get_validation_times(df_result, node_info)
    # print(f"Validation times: {validation_times}")
    mean_validation_time = get_avg_validation_time(validation_times)

    var_validation_time = get_validation_time_var(validation_times)

    requested_ledger_hashes, num_getledger_messages = get_getledger_stats(df_action)
    



    # 读取 aggregated_spec_check_log.json（注意：这是一个对象，不是数组）
    aggregate_spec_check_path = f"{log_dir}/aggregated_spec_check_log.json"
    if not os.path.exists(aggregate_spec_check_path):
        print(
            f"Aggregated spec check log file {aggregate_spec_check_path} does not exist."
        )
        return None

    with open(aggregate_spec_check_path, "r") as f:
        agg_spec_check = json.load(f)

    # 直接从字典中提取失败计数
    total_failures = agg_spec_check.get("failed_termination", 0) + agg_spec_check.get(
        "failed_agreement", 0
    )
    correct_runs = agg_spec_check.get("correct_runs", 0)
    failed_final_agreement = agg_spec_check.get("failed_final_agreement", 0)
    failed_agreement = agg_spec_check.get("failed_agreement", 0)

    test_duration = get_test_total_time(df_action)

    return {
        "test_duration": test_duration,
        "propose_set_count": propose_set_count,
        "mean_validation_time": mean_validation_time,
        "var_validation_time": var_validation_time,
        "total_failures": total_failures,
        "correct_runs": correct_runs,
        "failed_final_agreement": failed_final_agreement,
        "failed_agreement": failed_agreement,
        "num_getledger_hashes": len(requested_ledger_hashes),
        "num_getledger_messages": num_getledger_messages,
        "agg_spec_check": agg_spec_check,
    }


if __name__ == "__main__":
    res = evaluate_log(
        "/home/luanli/rocket_before_4_1/logs/2026_02_02_00h24m/G0T1", byzz_nodes=[3]
    )
    for k, v in res.items():
        print(f"{k}: {v}")
