import sys
import os
import argparse
import pandas as pd
import numpy as np


import json
import re
import codecs
from contextlib import redirect_stdout
from concurrent.futures import ProcessPoolExecutor
from collections import Counter
from io import StringIO
from pathlib import Path
from typing import Tuple, Set
from itertools import combinations
import yaml
from utils import *

# Ensure project root is on sys.path so local packages like 'protos' can be imported

repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
# Retry import; if it still fails, let the exception propagate so the caller can see the underlying issue
from evo.preferred import get_max_tip_distance, get_sum_tip_distance
from protos.packet_pb2 import Packet as ProtoPacket
from rocket_controller.encoder_decoder import (
    PacketEncoderDecoder,
    DecodingNotSupportedError,
)

# Ripple base58 alphabet (used for node public key encoding)
RIPPLE_ALPHABET = b"rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz"

# Weights for consensus-relevant message types when building the effective
# gossip connectivity graph from action logs.
GOSSIP_MESSAGE_WEIGHTS = {
    "TMValidation": 1.0,
    "TMProposeSet": 1.0,
    "TMStatusChange": 0.5,
    "TMHaveTransactionSet": 0.3,
    "TMGetLedger": 0.2,
    "TMLedgerData": 0.2,
}


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


def get_trusted_nodes_from_config(network_config: dict) -> dict[int, set[int]]:
    """Parse receiver-specific trusted validator sets from network config.

    ``unl_partition`` is stored in YAML as directional rows of the form
    ``[receiver_id, trusted_1, trusted_2, ...]``. For evaluation we treat the
    logical trusted set as including the receiver itself, matching the older
    offline analysis helpers and XRPL's effective-UNL mental model.
    """
    num_nodes = int(network_config.get("number_of_nodes", 0) or 0)
    unl_partitions = network_config.get("unl_partition") or []

    if unl_partitions:
        trusted_nodes = {}
        for partition in unl_partitions:
            if not partition:
                continue
            receiver_id = int(partition[0])
            trusted_nodes[receiver_id] = {
                receiver_id,
                *(int(node_id) for node_id in partition[1:]),
            }

        if num_nodes > 0:
            for node_id in range(num_nodes):
                trusted_nodes.setdefault(node_id, {node_id})
        return trusted_nodes

    if num_nodes <= 0:
        return {}

    # Empty unl_partition means fully connected trust.
    return {node_id: set(range(num_nodes)) for node_id in range(num_nodes)}


def get_trusted_nodes(log_dir: Path) -> dict[int, set[int]] | None:
    network_config_path = log_dir / "network_input.yaml"
    if not network_config_path.exists():
        print(f"Network config file {network_config_path} does not exist.")
        return None

    with open(network_config_path, "r") as f:
        network_config = yaml.safe_load(f) or {}

    return get_trusted_nodes_from_config(network_config)


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
        if pd.isna(packet_hex) or not packet_hex:
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


def get_diff_validation_time_max(vt: dict) -> float:
    diffs = []
    seq = set()
    for r in vt.values():
        seq.update(r.keys())
    for s in seq:
        times = []
        for _, r in vt.items():
            if s in r:
                times.append(r[s])
        if len(times) > 1:
            diffs.append(max(times) - min(times))

    return max(diffs) if diffs else None


def get_validation_distribution(
    df,
    node_info,
    byzz_nodes: list = None,
):
    distribution = {}  # node_id -> {ledger_index -> {node_id: hash}}
    byzz_set = {int(node_id) for node_id in (byzz_nodes or [])}

    # 读取每一行，如果是TM Validation，则反序列化为packet data，然后用serialize库解析validation消息

    for _, row in df.iterrows():
        if row["message_type"] != "TMValidation":
            continue

        # Prefer using the raw packet bytes logged in the 'packet_data' column
        packet_hex = row.get("packet_data")
        if pd.isna(packet_hex) or not packet_hex:
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
        if receiver_id in byzz_set:
            # 跳过拜占庭节点
            continue
        ledger_index = parsed.get("LedgerSequence")
        ledger_hash = parsed.get("LedgerHash")
        distribution.setdefault(receiver_id, {}).setdefault(ledger_index, {})[
            sender_id
        ] = ledger_hash

    return distribution


def get_validation_distribution_unl(
    df,
    node_info,
    byzz_nodes: list | None = None,
    trusted_nodes: dict[int, set[int]] | None = None,
):
    distribution = {}  # node_id -> {ledger_index -> {node_id: hash}}
    byzz_set = {int(node_id) for node_id in (byzz_nodes or [])}

    # 读取每一行，如果是TM Validation，则反序列化为packet data，然后用serialize库解析validation消息

    for _, row in df.iterrows():
        if row["message_type"] != "TMValidation":
            continue

        # Evaluate what the receiver actually saw after mutation, if available.
        packet_hex = row.get("possibly_mutated_packet_data")
        if pd.isna(packet_hex) or not packet_hex:
            packet_hex = row.get("packet_data")
        if pd.isna(packet_hex) or not packet_hex:
            print("No packet_data found for TMValidation message; skipping.")
            continue

        try:
            packet_bytes = bytes.fromhex(packet_hex)
            packet = ProtoPacket(data=packet_bytes)
            message, _ = PacketEncoderDecoder.decode_packet(packet)
            parsed = PacketEncoderDecoder.decode_validation(message)
        except (ValueError, DecodingNotSupportedError, Exception):
            continue

        pubkey = parsed.get("SigningPubKey")
        if not pubkey:
            continue

        sender_id = pub_key_to_node_id(pubkey, node_info)
        if sender_id is None:
            continue

        ledger_index = parsed.get("LedgerSequence")
        ledger_hash = parsed.get("LedgerHash")

        # A node implicitly trusts itself, so include its own signed validation
        # in its local view exactly once.
        if sender_id not in byzz_set and (
            trusted_nodes is None or sender_id in trusted_nodes.get(sender_id, set())
        ):
            distribution.setdefault(sender_id, {}).setdefault(ledger_index, {})[
                sender_id
            ] = ledger_hash

        receiver_id = row.get("to_node_id")
        if pd.isna(receiver_id):
            continue
        receiver_id = int(receiver_id)
        if receiver_id in byzz_set:
            continue

        if trusted_nodes is not None and sender_id not in trusted_nodes.get(
            receiver_id, set()
        ):
            continue

        distribution.setdefault(receiver_id, {}).setdefault(ledger_index, {})[
            sender_id
        ] = ledger_hash

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


def get_validation_distribution_entropies(validation_distribution):
    # input(f"validation_distribution: {validation_distribution}")
    entropies = []
    # 对每个节点的每个ledger index的validation分布进行评估，计算信息熵
    # 注意 validation_distribution 的结构是 node -> ledger_index -> {node_id: hash}
    for _, ledger_dict in validation_distribution.items():
        for _, validations in ledger_dict.items():
            hash_counts = {}
            total = 0
            for _, ledger_hash in validations.items():
                if ledger_hash not in hash_counts:
                    hash_counts[ledger_hash] = 0
                hash_counts[ledger_hash] += 1
                total += 1

            entropy = 0.0
            for count in hash_counts.values():
                p = count / total
                entropy -= p * np.log2(p)
            entropies.append(entropy)

    return entropies


def get_validation_distribution_entropy(validation_distribution):
    entropies = get_validation_distribution_entropies(validation_distribution)
    return np.mean(entropies) if entropies else None


def get_validation_distribution_entropy_max(validation_distribution):
    entropies = get_validation_distribution_entropies(validation_distribution)
    return np.max(entropies) if entropies else None


def get_proposal_distribution(df, node_info, byzz_nodes: list | None = None):
    """Build receiver-view proposal observations keyed by proposal round.

    We identify the real proposer via ``nodePubKey`` inside ``TMProposeSet``,
    not via ``from_node_id`` in the CSV row, because proposals can be relayed by
    gossip and the transport sender may not be the original proposer.

    Returned structure:
        receiver_id -> previousledger_hex -> propose_seq -> proposer_id -> {
            "timestamp": int,
            "current_tx_hash": str,
        }
    """
    distribution = {}
    byzz_set = {int(node_id) for node_id in (byzz_nodes or [])}

    for _, row in df.iterrows():
        if row["message_type"] != "TMProposeSet":
            continue

        packet_hex = row.get("possibly_mutated_packet_data")
        if pd.isna(packet_hex) or not packet_hex:
            packet_hex = row.get("packet_data")
        if pd.isna(packet_hex) or not packet_hex:
            continue

        try:
            packet_bytes = bytes.fromhex(packet_hex)
            packet = ProtoPacket(data=packet_bytes)
            message, _ = PacketEncoderDecoder.decode_packet(packet)
        except (ValueError, DecodingNotSupportedError, Exception):
            continue

        receiver_id = row.get("to_node_id")
        if pd.isna(receiver_id):
            continue
        receiver_id = int(receiver_id)
        if receiver_id in byzz_set:
            continue

        proposer_id = pub_key_to_node_id(message.nodePubKey.hex(), node_info)
        if proposer_id is None:
            continue
        if proposer_id == receiver_id:
            # A node's own proposal can be relayed back to it in gossip, but we
            # only want peer proposal confusion here.
            continue

        previous_ledger = bytes(message.previousledger).hex()
        propose_seq = int(message.proposeSeq)
        timestamp = int(row.get("timestamp", 0) or 0)
        current_tx_hash = bytes(message.currentTxHash).hex()

        receiver_entry = distribution.setdefault(receiver_id, {})
        ledger_entry = receiver_entry.setdefault(previous_ledger, {})
        seq_entry = ledger_entry.setdefault(propose_seq, {})

        # Keep the latest observation for each proposer at this receiver/round.
        existing = seq_entry.get(proposer_id)
        if existing is None or timestamp >= existing["timestamp"]:
            seq_entry[proposer_id] = {
                "timestamp": timestamp,
                "current_tx_hash": current_tx_hash,
            }

    return distribution


def get_proposal_distribution_entropy(proposal_distribution):
    """Compute a discrete integral of proposal entropy over proposal rounds.

    For each ``receiver × previousledger`` pair we walk proposeSeq in order,
    maintain the latest proposal seen from each proposer, compute the entropy of
    the resulting ``currentTxHash`` distribution, and sum that entropy over the
    discrete proposal rounds. A higher score means disagreement persists longer
    instead of quickly collapsing toward one proposal.
    """
    integrals = []

    for _, ledger_dict in proposal_distribution.items():
        for _, seq_dict in ledger_dict.items():
            if not seq_dict:
                continue

            latest_by_proposer = {}
            round_integral = 0.0
            # Iterate only over observed proposal sequence values. Ripple logs
            # can contain sentinel / wrapped values such as 4294967295; using a
            # dense numeric range would expand that into billions of empty
            # iterations and effectively hang evaluation.
            for seq in sorted(seq_dict.keys()):
                updates = seq_dict[seq]
                for proposer_id, proposal in updates.items():
                    latest_by_proposer[proposer_id] = proposal["current_tx_hash"]

                if not latest_by_proposer:
                    continue

                hash_counts = {}
                total = 0
                for tx_hash in latest_by_proposer.values():
                    hash_counts[tx_hash] = hash_counts.get(tx_hash, 0) + 1
                    total += 1

                entropy = 0.0
                for count in hash_counts.values():
                    p = count / total
                    entropy -= p * np.log2(p)
                round_integral += entropy

            integrals.append(round_integral)

    return np.mean(integrals) if integrals else None


def build_gossip_connectivity_matrix(
    df_exec: pd.DataFrame,
    node_info: dict,
    byzz_nodes: list | None = None,
    message_weights: dict[str, float] | None = None,
) -> tuple[np.ndarray, list[int]]:
    """Build an undirected weighted communication matrix among honest nodes.

    The matrix is derived from action logs, with edge weights reflecting the
    amount of consensus-relevant traffic observed between node pairs. We keep
    isolated honest nodes in the matrix so the resulting Fiedler value drops to
    zero when the effective communication graph becomes disconnected.
    """
    byzz_set = {int(node_id) for node_id in (byzz_nodes or [])}
    weights = message_weights or GOSSIP_MESSAGE_WEIGHTS

    honest_nodes = sorted(
        int(node_id) for node_id in node_info.keys() if int(node_id) not in byzz_set
    )
    node_to_idx = {node_id: idx for idx, node_id in enumerate(honest_nodes)}
    matrix = np.zeros((len(honest_nodes), len(honest_nodes)), dtype=float)

    if matrix.size == 0:
        return matrix, honest_nodes

    for _, row in df_exec.iterrows():
        msg_type = row.get("message_type")
        msg_weight = weights.get(msg_type, 0.0)
        if msg_weight <= 0:
            continue

        from_node = row.get("from_node_id")
        to_node = row.get("to_node_id")
        if pd.isna(from_node) or pd.isna(to_node):
            continue

        try:
            from_node = int(from_node)
            to_node = int(to_node)
        except (TypeError, ValueError):
            continue

        if from_node == to_node:
            continue
        if from_node not in node_to_idx or to_node not in node_to_idx:
            continue

        send_amount = row.get("send_amount", 1)
        try:
            send_amount = float(send_amount)
        except (TypeError, ValueError):
            send_amount = 1.0

        if send_amount <= 0:
            continue

        matrix[node_to_idx[from_node], node_to_idx[to_node]] += (
            msg_weight * send_amount
        )

    # Use a symmetric matrix so the Laplacian matches the standard Fiedler
    # definition for undirected weighted graphs.
    matrix = (matrix + matrix.T) / 2.0
    return matrix, honest_nodes


def get_gossip_fiedler(
    df_exec: pd.DataFrame,
    node_info: dict,
    byzz_nodes: list | None = None,
    message_weights: dict[str, float] | None = None,
) -> float:
    """Return a maximization-friendly Fiedler score for the honest gossip graph.

    We maximize fitness in DEAP, but a smaller raw Fiedler value means the
    graph is more fragile / closer to disconnecting. Return the negated value
    so higher fitness prefers more fragile connectivity.
    """
    matrix, honest_nodes = build_gossip_connectivity_matrix(
        df_exec,
        node_info=node_info,
        byzz_nodes=byzz_nodes,
        message_weights=message_weights,
    )

    if len(honest_nodes) < 2:
        return 0.0

    degree = np.sum(matrix, axis=1)
    laplacian = np.diag(degree) - matrix
    eigenvalues = np.linalg.eigvalsh(laplacian)
    eigenvalues = np.clip(eigenvalues, 0.0, None)
    return -float(eigenvalues[1]) if len(eigenvalues) > 1 else 0.0


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
        df = pd.read_csv(
            f,
            dtype={
                "message_type": "string",
                "packet_data": "string",
                "possibly_mutated_packet_data": "string",
                "original_data": "string",
                "possibly_mutated_data": "string",
            },
        )

    df = df["timestamp"]
    if df.empty:
        print("No timestamps found.")
        return None
    return (df.max() - df.min()) / 1000.0


def get_node_info(log_dir: Path):
    node_info_path = log_dir / "iteration-1" / "node_info-1.csv"
    if not node_info_path.exists():
        print(f"Node info file {node_info_path} does not exist.")
        return None
    df_node_info = pd.read_csv(node_info_path)
    # 返回 {node_id: (private_key, public_key)}
    return {
        row["node_id"]: (row["private_key"], row["public_key"])
        for _, row in df_node_info.iterrows()
    }


FITNESS_FUNCTIONS = [
    "num_propose_set",
    "num_getledger_hashes",
    "num_getledger_messages",
    "mean_validation_time",
    "var_validation_time",
    "diff_validation_time_max",
    "validation_distribution_entropy",
    "validation_distribution_entropy_max",
    "validation_distribution_entropy_unl",
    "validation_distribution_entropy_max_unl",
    "proposal_distribution_entropy",
    "message_entropy_integral",
    "message_entropy_average",
    "markov_matrix_non_similarity",
    "gossip_fiedler",
    "max_tip_distance",
    "sum_tip_distance",
]


def evaluate_log(log_dir: Path, byzz_nodes: list):

    res = {i: None for i in FITNESS_FUNCTIONS}

    node_info = get_node_info(log_dir)
    print(f"Node info: {node_info}")
    trusted_nodes = get_trusted_nodes(log_dir)

    # 如果存在 log_dir/iteration-1/action-1.csv，则进行评估
    action_log_path = log_dir / "iteration-1" / "action-1.csv"
    if not action_log_path.exists():
        print(f"Action log file {action_log_path} does not exist.")
        return None
    df_action = pd.read_csv(
        action_log_path,
        dtype={
            "message_type": "string",
            "packet_data": "string",
            "possibly_mutated_packet_data": "string",
            "original_data": "string",
            "possibly_mutated_data": "string",
        },
    )
    # 计算 "message_type"为"TMProposeSet" 的行数
    num_propose_set = get_prop_set_count(df_action)
    res["num_propose_set"] = num_propose_set

    result_log_path = log_dir / "iteration-1" / "result-1.csv"
    if not result_log_path.exists():
        print(f"Result log file {result_log_path} does not exist.")
        return None
    df_result = pd.read_csv(
        result_log_path,
        dtype={
            "ledger_hash": "string",
        },
    )
    validation_times = get_validation_times(df_result, node_info)
    # print(f"Validation times: {validation_times}")
    mean_validation_time = get_avg_validation_time(validation_times)
    res["mean_validation_time"] = mean_validation_time

    var_validation_time = get_validation_time_var(validation_times)
    res["var_validation_time"] = var_validation_time

    diff_validation_time_max = get_diff_validation_time_max(validation_times)
    res["diff_validation_time_max"] = diff_validation_time_max
    print(f"Diff validation time max: {diff_validation_time_max}")

    requested_ledger_hashes, num_getledger_messages = get_getledger_stats(df_action)
    num_getledger_hashes = len(requested_ledger_hashes)
    res["num_getledger_hashes"] = num_getledger_hashes
    res["num_getledger_messages"] = num_getledger_messages

    validation_distribution = get_validation_distribution(df_action, node_info, byzz_nodes)
    validation_distribution_entropy = get_validation_distribution_entropy(
        validation_distribution
    )
    print(f"Validation distribution entropy: {validation_distribution_entropy}")
    res["validation_distribution_entropy"] = validation_distribution_entropy

    validation_distribution_entropy_max = get_validation_distribution_entropy_max(
        validation_distribution
    )
    print(
        "Validation distribution entropy max: "
        f"{validation_distribution_entropy_max}"
    )
    res["validation_distribution_entropy_max"] = (
        validation_distribution_entropy_max
    )

    validation_distribution_unl = get_validation_distribution_unl(
        df_action,
        node_info,
        byzz_nodes,
        trusted_nodes=trusted_nodes,
    )
    validation_distribution_entropy_unl = get_validation_distribution_entropy(
        validation_distribution_unl
    )
    print(
        "Validation distribution entropy UNL: "
        f"{validation_distribution_entropy_unl}"
    )
    res["validation_distribution_entropy_unl"] = (
        validation_distribution_entropy_unl
    )

    validation_distribution_entropy_max_unl = (
        get_validation_distribution_entropy_max(validation_distribution_unl)
    )
    print(
        "Validation distribution entropy max UNL: "
        f"{validation_distribution_entropy_max_unl}"
    )
    res["validation_distribution_entropy_max_unl"] = (
        validation_distribution_entropy_max_unl
    )

    proposal_distribution = get_proposal_distribution(
        df_action, node_info, byzz_nodes
    )
    proposal_distribution_entropy = get_proposal_distribution_entropy(
        proposal_distribution
    )
    print(f"Proposal distribution entropy: {proposal_distribution_entropy}")
    res["proposal_distribution_entropy"] = proposal_distribution_entropy

    message_entropy_integral, message_entropy_average = get_message_entropy_integration(
        df_action
    )
    res["message_entropy_integral"] = message_entropy_integral
    res["message_entropy_average"] = message_entropy_average
    print(f"Message entropy integral: {message_entropy_integral}")
    print(f"Message entropy average: {message_entropy_average}")

    markov_matrix_non_similarity = get_msg_sending_markov_matrix_non_similarity(
        df_action
    )
    res["markov_matrix_non_similarity"] = markov_matrix_non_similarity
    print(f"Markov matrix non-similarity: {markov_matrix_non_similarity}")

    gossip_fiedler = get_gossip_fiedler(
        df_action,
        node_info=node_info,
        byzz_nodes=byzz_nodes,
    )
    res["gossip_fiedler"] = gossip_fiedler
    print(f"Gossip Fiedler value: {gossip_fiedler}")

    max_tip_distance = get_max_tip_distance(log_dir)
    res["max_tip_distance"] = max_tip_distance
    print(f"Max tip distance: {max_tip_distance}")

    sum_tip_distance = get_sum_tip_distance(log_dir)
    res["sum_tip_distance"] = sum_tip_distance
    print(f"Sum tip distance: {sum_tip_distance}")

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


def _looks_like_gxtx_log_dir(path: Path) -> bool:
    """Return whether ``path`` looks like one saved GxTx run directory."""
    if not path.is_dir():
        return False
    if re.fullmatch(r"G\d+T\d+", path.name) is None:
        return False

    return any(
        marker.exists()
        for marker in (
            path / "network_input.yaml",
            path / "aggregated_spec_check_log.json",
            path / "iteration-1",
        )
    )


def collect_gxtx_dirs_from_logs_dir(root_dir: Path) -> list[Path]:
    """Find GxTx run directories under a logs root using the expected layout."""
    candidates: set[Path] = set()
    if _looks_like_gxtx_log_dir(root_dir):
        candidates.add(root_dir.resolve())

    for pattern in (
        "G*T*",
        "*/G*T*",
        "*/*/G*T*",
        "*/*/*/G*T*",
        "*/*/*/*/G*T*",
    ):
        for candidate in root_dir.glob(pattern):
            if _looks_like_gxtx_log_dir(candidate):
                candidates.add(candidate.resolve())

    if candidates:
        return sorted(candidates)

    return sorted(
        path.resolve()
        for path in root_dir.rglob("*")
        if _looks_like_gxtx_log_dir(path)
    )


def resolve_jobs(requested_jobs: int | None, num_tasks: int) -> int:
    """Resolve the effective worker count for batch evaluation."""
    if num_tasks <= 1:
        return 1
    if requested_jobs is not None:
        return max(1, min(requested_jobs, num_tasks))

    cpu_count = os.cpu_count() or 1
    return max(1, min(num_tasks, cpu_count))


def find_latest_log_dir() -> Path | None:
    """Locate the newest child directory under the configured logs root."""
    logs_root = get_logs_root(Path(repo_root))
    if not logs_root.exists():
        return None

    subdirs = [path for path in logs_root.iterdir() if path.is_dir()]
    if not subdirs:
        return None

    return max(subdirs, key=lambda path: path.stat().st_mtime)


def _get_run_metadata(root_dir: Path, log_dir: Path) -> dict[str, str]:
    """Infer image / encoding / fitness labels relative to the chosen root."""
    try:
        relative_parts = log_dir.resolve().relative_to(root_dir.resolve()).parts
    except ValueError:
        relative_parts = log_dir.parts

    image = ""
    encoding = ""
    fitness = ""

    if len(relative_parts) >= 4:
        image = relative_parts[-4]
        encoding = relative_parts[-3]
        fitness = relative_parts[-2]
    elif len(relative_parts) == 3:
        image = root_dir.name
        encoding = relative_parts[0]
        fitness = relative_parts[1]
    elif len(relative_parts) == 2:
        image = root_dir.parent.name if len(root_dir.parents) >= 1 else ""
        encoding = root_dir.name
        fitness = relative_parts[0]
    elif len(relative_parts) == 1 and not _looks_like_gxtx_log_dir(root_dir):
        image = root_dir.parents[1].name if len(root_dir.parents) >= 2 else ""
        encoding = root_dir.parent.name if len(root_dir.parents) >= 1 else ""
        fitness = root_dir.name

    return {
        "image": image,
        "encoding": encoding,
        "fitness": fitness,
        "test_case": log_dir.name,
    }


def _get_byzz_nodes_for_log_dir(log_dir: Path) -> list[int]:
    """Read byzantine node ids from one saved run directory when available."""
    network_config_path = log_dir / "network_input.yaml"
    if not network_config_path.exists():
        return []

    with open(network_config_path, "r") as f:
        network_config = yaml.safe_load(f) or {}

    return [int(node_id) for node_id in (network_config.get("byzz_nodes") or [])]


def _evaluate_single_log_dir(task: tuple[Path, Path]) -> dict:
    """Evaluate one saved run while keeping worker stdout out of the main log."""
    root_dir, log_dir = task
    row = {
        **_get_run_metadata(root_dir, log_dir),
        **{fitness_name: None for fitness_name in FITNESS_FUNCTIONS},
    }
    captured_stdout = StringIO()

    try:
        byzz_nodes = _get_byzz_nodes_for_log_dir(log_dir)
        with redirect_stdout(captured_stdout):
            result = evaluate_log(log_dir, byzz_nodes=byzz_nodes)
        if result is None:
            return {
                "row": row,
                "log_dir": str(log_dir),
                "error": "evaluate_log returned None",
                "stdout": captured_stdout.getvalue(),
            }

        for fitness_name in FITNESS_FUNCTIONS:
            row[fitness_name] = result.get(fitness_name)
        return {
            "row": row,
            "log_dir": str(log_dir),
            "error": None,
            "stdout": "",
        }
    except Exception as exc:
        return {
            "row": row,
            "log_dir": str(log_dir),
            "error": f"{type(exc).__name__}: {exc}",
            "stdout": captured_stdout.getvalue(),
        }


def _sanitize_output_stem(name: str) -> str:
    """Return a filesystem-friendly stem for the batch CSV filename."""
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", name).strip("._")
    return sanitized or "logs"


def _default_batch_output_path(root_dir: Path) -> Path:
    """Build the default batch-evaluation CSV path under evo/tmp."""
    tmp_dir = Path(__file__).resolve().parent / "tmp"
    return tmp_dir / f"evaluate_{_sanitize_output_stem(root_dir.name)}_{get_date_time_strf()}.csv"


def run_batch_evaluation(
    root_dir: Path,
    output_path: Path,
    jobs: int | None = None,
) -> int:
    """Evaluate all discovered GxTx runs under ``root_dir`` and write one CSV."""
    gxtx_dirs = collect_gxtx_dirs_from_logs_dir(root_dir)
    if not gxtx_dirs:
        print(f"❌ 在 {root_dir} 下没有找到 GxTx 日志目录。")
        return 1

    worker_count = resolve_jobs(jobs, len(gxtx_dirs))
    print(f"📂 搜索根目录: {root_dir}")
    print(f"🧪 发现 {len(gxtx_dirs)} 个 GxTx 日志目录")
    print(f"🚀 并行 worker 数: {worker_count}")
    tasks = [(root_dir, log_dir) for log_dir in gxtx_dirs]

    if worker_count == 1:
        results = [_evaluate_single_log_dir(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            results = list(executor.map(_evaluate_single_log_dir, tasks))

    rows = [result["row"] for result in results]
    failures = [result for result in results if result["error"]]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_columns = ["image", "encoding", "fitness", "test_case", *FITNESS_FUNCTIONS]
    pd.DataFrame(rows, columns=output_columns).to_csv(output_path, index=False)

    print(f"📝 已写出 {len(rows)} 行到 {output_path}")
    if failures:
        print(f"⚠️  {len(failures)} 个日志目录评估失败，已保留空指标行：")
        error_counts = Counter(result["error"] for result in failures)
        for error, count in error_counts.most_common():
            print(f"  - {count} × {error}")

        preview_count = min(10, len(failures))
        print(f"🔎 失败样本预览（前 {preview_count} 个）:")
        for result in failures[:preview_count]:
            print(f"  - {result['log_dir']}: {result['error']}")
        if len(failures) > preview_count:
            print(f"  - ... 其余 {len(failures) - preview_count} 个失败样本已省略")
    else:
        print("✅ 所有日志目录评估完成。")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="从日志根目录批量搜索 GxTx 并调用 evaluate_log，输出调试 CSV。"
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="日志顶层目录；若不提供则自动搜索最新日志目录。",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="输出 CSV 路径；默认写到 evo/tmp/evaluate_<root>_<timestamp>.csv",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        help="并行 worker 数；默认自动选择，传 1 可禁用并行。",
    )
    args = parser.parse_args()

    if args.input is None:
        root_dir = find_latest_log_dir()
        if root_dir is None:
            print("❌ 未找到最新日志目录。")
            return 1
    else:
        root_dir = Path(args.input).expanduser().resolve()
        if not root_dir.exists():
            print(f"❌ 输入路径不存在: {root_dir}")
            return 1

    output_path = (
        args.output.expanduser().resolve()
        if args.output is not None
        else _default_batch_output_path(root_dir)
    )
    return run_batch_evaluation(root_dir, output_path, jobs=args.jobs)


if __name__ == "__main__":
    sys.exit(main())
