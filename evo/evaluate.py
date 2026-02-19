import sys
import os
import pandas as pd
import numpy as np
import json
import re
import codecs
from typing import Tuple, Set
from itertools import combinations
from utils import *

# Ensure project root is on sys.path so local packages like 'protos' can be imported

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
# Retry import; if it still fails, let the exception propagate so the caller can see the underlying issue
from protos.packet_pb2 import Packet as ProtoPacket
from rocket_controller.encoder_decoder import (
    PacketEncoderDecoder,
    DecodingNotSupportedError,
)

# Ripple base58 alphabet (used for node public key encoding)
RIPPLE_ALPHABET = b"rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz"


def base58_encode_ripple(data: bytes) -> str:
    """Encode data using Ripple's base58 alphabet."""
    num = int.from_bytes(data, byteorder="big")

    encoded = []
    while num > 0:
        num, remainder = divmod(num, 58)
        encoded.append(RIPPLE_ALPHABET[remainder])

    # Add leading zeros
    for byte in data:
        if byte == 0:
            encoded.append(RIPPLE_ALPHABET[0])
        else:
            break

    return bytes(reversed(encoded)).decode("ascii")


def public_key_bytes_to_node_public_key(pubkey_bytes: bytes) -> str:
    """Convert raw public key bytes (compressed secp256k1 or ed25519) to
    Ripple node public key string (base58 with node-public prefix and checksum).

    This matches the encoding used in node info files where validation/public
    keys are stored as strings like 'n9...'.
    """
    import hashlib

    # Node public key type prefix used by Ripple for node public keys
    prefix = b"\x1c"
    payload = prefix + pubkey_bytes

    # double-sha256 checksum
    hash1 = hashlib.sha256(payload).digest()
    hash2 = hashlib.sha256(hash1).digest()
    checksum = hash2[:4]

    return base58_encode_ripple(payload + checksum)


def pub_key_to_node_id(pubkey_bytes: str, node_info: dict) -> int:
    """Convert a public key (bytes) to the node_id using node_info mapping.

    node_info is expected to be the dict returned by `get_node_info`, i.e.
    { node_id: (private_key, public_key_string) } where public_key_string is
    the base58-encoded Ripple node public key (like 'n9...').

    Returns the matching node_id (int) or None if not found.
    """
    key_str = public_key_bytes_to_node_public_key(bytes.fromhex(pubkey_bytes))

    for node_id, (_, pub) in node_info.items():
        if pub == key_str:
            return node_id
    return None


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


# fully validated
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


def get_validation_distribution(df, node_info, byzz_nodes: list = None):
    distribution = {}  # node_id -> {ledger_index -> {node_id: hash}}

    # 读取每一行，如果是TM Validation，则反序列化为packet data，然后用serialize库解析validation消息

    for _, row in df.iterrows():
        if row["message_type"] != "TMValidation":
            continue

        # Prefer using the raw packet bytes logged in the 'packet_data' column
        packet_hex = row.get("packet_data")
        if not packet_hex or pd.isna(packet_hex):
            # If packet_data is missing, skip this row (avoid string parsing)
            print("No packet_data found for TMValidation message; skipping.")
            continue

        packet_bytes = bytes.fromhex(packet_hex)
        packet = ProtoPacket(data=packet_bytes)
        message, msg_type = PacketEncoderDecoder.decode_packet(packet)

        parsed = PacketEncoderDecoder.decode_validation(message)

        pubkey = parsed.get("SigningPubKey")
        sender_id = pub_key_to_node_id(pubkey, node_info)
        receiver_id = row["to_node_id"]
        if receiver_id in byzz_nodes:
            # 跳过拜占庭节点
            continue
        ledger_index = parsed.get("LedgerSequence")
        hash = parsed.get("LedgerHash")
        distribution.setdefault(receiver_id, {}).setdefault(ledger_index, {})[
            sender_id
        ] = hash

    # for _, row in df.iterrows():
    #     if row["validation_parsed"] is None:
    #         # 跳过拜占庭节点
    #         continue

    #     pubkey_hex = row["validation_parsed"]["SigningPubKey"]  # 十六进制字符串
    #     # 将十六进制字符串转换为 bytes
    #     pubkey_bytes = bytes.fromhex(pubkey_hex)
    #     sender_id = pub_key_to_node_id(pubkey_bytes, node_info)

    #     if sender_id is None:
    #         # 无法识别的公钥，跳过
    #         continue
    #     # input(f"sender_id: {sender_id}")
    #     for node in trusted_nodes.keys():
    #         if sender_id not in trusted_nodes[node]:
    #             continue
    #         ledger_index = row["validation_parsed"]["LedgerSequence"]
    #         ledger_hash_bytes = bytes.fromhex(row["validation_parsed"]["LedgerHash"])
    #         ledger_hash = ledger_hash_bytes.hex()
    #         if node not in distribution:
    #             distribution[node] = {}
    #         if ledger_index not in distribution[node]:
    #             distribution[node][ledger_index] = {}
    #         distribution[node][ledger_index][sender_id] = ledger_hash

    return distribution


def get_validation_distribution_entropy(validation_distribution):
    # input(f"validation_distribution: {validation_distribution}")
    ent = []
    # 对每个节点的每个ledger index的validation分布进行评估，计算信息熵，然后求平均值
    # 注意 validation_distribution 的结构是 node -> ledger_index -> {node_id: hash}
    for node, ledger_dict in validation_distribution.items():
        for ledger_index, validations in ledger_dict.items():
            # 计算这个 validations 的信息熵
            hash_counts = {}
            total = 0
            for node_id, hash in validations.items():
                if hash not in hash_counts:
                    hash_counts[hash] = 0
                hash_counts[hash] += 1
                total += 1
            # 计算信息熵
            entropy = 0
            for count in hash_counts.values():
                p = count / total
                entropy -= p * np.log2(p)
            ent.append(entropy)
    return np.mean(ent) if ent else None


# 对每个时间窗口内发送的消息，根据类型分组，计算信息熵
def get_message_entropy_integration(df_exec):
    integral = 0
    start_time = df_exec["timestamp"].min()
    end_time = df_exec["timestamp"].max()
    window_size = 100  # 0.1 second windows
    for window_start in range(start_time, end_time, window_size):
        window_end = window_start + window_size
        df_window = df_exec[
            (df_exec["timestamp"] >= window_start) & (df_exec["timestamp"] < window_end)
        ]
        if df_window.empty:
            continue
        # 计算消息类型的频率分布
        type_counts = df_window["message_type"].value_counts()
        total_count = type_counts.sum()
        probabilities = type_counts / total_count
        # 计算信息熵
        entropy = -np.sum(probabilities * np.log2(probabilities))
        # 积分（简单累加）
        integral += entropy * (window_size / 1000.0)  # 转换为秒
    return integral, integral / ((end_time - start_time) / 1000.0)


# 对每个节点发送/接收的消息组成的序列，计算马尔可夫转移矩阵，然后求所有节点矩阵的相似度
def get_msg_sending_markov_matrix_non_similarity(df_exec):
    """
    计算所有节点马尔可夫转移矩阵的平均相似度

    参数:
        df_exec: DataFrame，包含'from_node_id'和'message_type'列

    返回:
        similarity: 所有节点间转移矩阵的平均相似度（0-1之间）
    """
    # 1. 按节点分组消息序列
    msg_by_node = {}  # from_node_id -> [message types]

    # 确保按时间顺序（如果DataFrame已按时间排序）
    df_sorted = (
        df_exec.sort_values(by="timestamp")
        if "timestamp" in df_exec.columns
        else df_exec
    )

    for _, row in df_sorted.iterrows():
        from_node = row["from_node_id"]
        message_type = row["message_type"]
        if from_node not in msg_by_node:
            msg_by_node[from_node] = []
        msg_by_node[from_node].append(message_type)

    # 2. 获取所有可能的消息类型
    all_message_types = sorted(df_exec["message_type"].unique())
    msg_to_idx = {msg: i for i, msg in enumerate(all_message_types)}
    n_types = len(all_message_types)

    # 3. 为每个节点构建转移矩阵
    node_matrices = {}

    for node, seq in msg_by_node.items():
        if len(seq) < 2:
            # 序列太短，无法计算转移矩阵
            # 使用均匀分布作为默认
            node_matrices[node] = np.ones((n_types, n_types)) / n_types
            continue

        # 初始化转移计数矩阵
        trans_counts = np.zeros((n_types, n_types))

        # 统计转移频次
        for i in range(len(seq) - 1):
            from_msg = seq[i]
            to_msg = seq[i + 1]
            from_idx = msg_to_idx[from_msg]
            to_idx = msg_to_idx[to_msg]
            trans_counts[from_idx, to_idx] += 1

        # 归一化为概率矩阵（处理全零行）
        trans_matrix = np.zeros((n_types, n_types))
        for i in range(n_types):
            row_sum = trans_counts[i].sum()
            if row_sum > 0:
                trans_matrix[i] = trans_counts[i] / row_sum
            else:
                # 如果某行全零，使用均匀分布
                trans_matrix[i] = np.ones(n_types) / n_types

        node_matrices[node] = trans_matrix

    # 4. 计算两两节点之间的矩阵相似度
    node_list = list(node_matrices.keys())

    if len(node_list) < 2:
        return 1.0  # 只有一个节点，相似度为1

    # 方法1：使用余弦相似度（展平为向量）
    similarities = []

    for node1, node2 in combinations(node_list, 2):
        mat1 = node_matrices[node1].flatten()
        mat2 = node_matrices[node2].flatten()

        # 余弦相似度
        dot_product = np.dot(mat1, mat2)
        norm1 = np.linalg.norm(mat1)
        norm2 = np.linalg.norm(mat2)

        if norm1 > 0 and norm2 > 0:
            cos_sim = dot_product / (norm1 * norm2)
            similarities.append(cos_sim)
        else:
            similarities.append(0.0)

    # 5. 返回平均相似度
    mean_similarity = np.mean(similarities) if similarities else 0.0

    return 1 - mean_similarity


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


def evaluate_log(log_dir, byzz_nodes: list):

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

    validation_distribution = get_validation_distribution(
        df_action, node_info, byzz_nodes
    )
    validation_distribution_entropy = get_validation_distribution_entropy(
        validation_distribution
    )
    print(f"Validation distribution entropy: {validation_distribution_entropy}")

    message_entropy_integral, message_entropy_average = get_message_entropy_integration(
        df_action
    )
    print(f"Message entropy integral: {message_entropy_integral}")
    print(f"Message entropy average: {message_entropy_average}")

    markov_matrix_non_similarity = get_msg_sending_markov_matrix_non_similarity(
        df_action
    )
    print(f"Markov matrix non-similarity: {markov_matrix_non_similarity}")

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

    # fitness part
    res = {
        "num_propose_set": propose_set_count,
        "num_getledger_hashes": len(requested_ledger_hashes),
        "num_getledger_messages": num_getledger_messages,
        "mean_validation_time": mean_validation_time,
        "var_validation_time": var_validation_time,
        "validation_distribution_entropy": validation_distribution_entropy,
        "message_entropy_integral": message_entropy_integral,
        "message_entropy_average": message_entropy_average,
        "markov_matrix_non_similarity": markov_matrix_non_similarity,
    }

    res.update(
        {
            "test_duration": test_duration,
            "total_failures": total_failures,
            "correct_runs": correct_runs,
            "failed_final_agreement": failed_final_agreement,
            "failed_agreement": failed_agreement,
            "agg_spec_check": agg_spec_check,
        }
    )

    return res


if __name__ == "__main__":
    res = evaluate_log(get_last_log_dir()/"G0T1", byzz_nodes=[3])
    for k, v in res.items():
        print(f"{k}: {v}")
