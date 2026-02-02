from pdb import run
import sys
from time import time
import pandas as pd
from pathlib import Path
import json
from serialize import parse_bytes
import os
import numpy as np
from itertools import combinations
import polars as pl
import re
from byzz_analyze import count, f_incompatible, f_insufficient, f_not, f_or, f_timeout

# pd.set_option("display.max_colwidth", None)     # 不截断列内容
# pd.set_option("display.width", 2000)      # 终端宽度（增大以避免换行）
# pd.set_option("display.max_columns", None)      # 显示所有列

byzz_nodes = [3]
UNL1 = [0, 1, 2, 3, 4]
UNL2 = [2, 3, 4, 5, 6]
trusted_nodes = {
    0: UNL1,
    1: UNL1,
    2: UNL1,
    4: UNL2,
    5: UNL2,
    6: UNL2,
}


nodeinfo = pd.read_csv("nodeinfo.csv")

# Ripple's base58 alphabet
RIPPLE_ALPHABET = b"rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz"


def base58_encode_ripple(data):
    """Encode data using Ripple's base58 alphabet"""
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


def public_key_bytes_to_node_public_key(pubkey_bytes):
    """Convert raw public key bytes to Ripple node public key format (base58)"""
    import hashlib

    # Add node public key type prefix (0x1C)
    payload = b"\x1c" + pubkey_bytes

    # Calculate checksum
    hash1 = hashlib.sha256(payload).digest()
    hash2 = hashlib.sha256(hash1).digest()
    checksum = hash2[:4]

    # Encode with checksum
    return base58_encode_ripple(payload + checksum)


def pub_key_to_node_id(pubkey_bytes):
    """Convert public key bytes to node_id using nodeinfo.csv mapping"""
    # Convert bytes to Ripple base58 format
    key = public_key_bytes_to_node_public_key(pubkey_bytes)

    # Find matching node_id in nodeinfo
    row = nodeinfo[nodeinfo["validation_public_key"] == key]
    if not row.empty:
        return int(row["node_id"].values[0])
    else:
        return None


def get_validation_times(df_lgrClosed, df_exec_sc, node_id):
    """优化版本：使用向量化操作"""
    validation_times = {}

    # 使用numpy向量化操作
    if len(df_lgrClosed) == 0:
        return validation_times

    # 提前提取需要的数据
    timestamps = df_lgrClosed["timestamp"].values
    messages = df_lgrClosed["message"].values

    # 预筛选df_exec_sc
    mask = (df_exec_sc["newEvent"] == "neCLOSING_LEDGER") & (
        df_exec_sc["from_node_id"] == node_id
    )
    df_match_filtered = df_exec_sc[mask]

    # 创建ledgerSeq到最小timestamp的映射
    ledger_to_tbegin = {}
    if not df_match_filtered.empty:
        for ledger_seq, t_begin in zip(
            df_match_filtered["ledgerSeq"], df_match_filtered["timestamp"]
        ):
            if (
                ledger_seq not in ledger_to_tbegin
                or t_begin < ledger_to_tbegin[ledger_seq]
            ):
                ledger_to_tbegin[ledger_seq] = t_begin

    # 处理每个ledgerClosed
    for t, msg in zip(timestamps, messages):
        msg_dict = json.loads(msg) if isinstance(msg, str) else msg
        ledger_index = msg_dict["ledger_index"]
        prev_index = ledger_index - 1

        if prev_index in ledger_to_tbegin:
            t_begin = ledger_to_tbegin[prev_index]
            validation_time = (t - t_begin) / 1000.0
            validation_times[ledger_index] = validation_time
    return validation_times


def get_fully_validated_hashes(df_lgrClosed, node_id):
    fully_validated_hashes = {}  # ledger_index -> hash
    for _, row in df_lgrClosed.iterrows():
        ledger_index = json.loads(row["message"])["ledger_index"]
        hash = json.loads(row["message"])["ledger_hash"]
        fully_validated_hashes[ledger_index] = hash
    return fully_validated_hashes


def get_disagree_ledger_indexes(fully_validated_hashes):
    disagree_ledger_indexes = []
    # 获取所有节点的fully_validated_hashes中的所有ledger_index的并集
    all_ledger_indexes = set()
    for node_hashes in fully_validated_hashes.values():
        all_ledger_indexes.update(node_hashes.keys())

    for ledger_index in all_ledger_indexes:
        hashes = set()
        for node_hashes in fully_validated_hashes.values():
            if ledger_index in node_hashes:
                hashes.add(node_hashes[ledger_index])
        if len(hashes) > 1:
            disagree_ledger_indexes.append(ledger_index)
    return disagree_ledger_indexes


def identify_violations(dir, res):
    """
    根据 results.txt 文件识别测试运行的结果类型
    填充 results["groups"] 列表
    """
    results_file = Path(dir) / "results.txt"
    results = open(results_file).readlines()

    if results[-1] != "done!\n":
        res["groups"].append("incomplete")
    elif results[4] == "reason: all committed\n":
        res["groups"].append("correct")
    elif results[4] == "reason: flags\n":
        flags = results[5:-1]
        if count(f_not(f_timeout), flags) == 0:
            res["groups"].append("timeout")
        elif (
            count(f_not(f_or(f_insufficient, f_timeout)), flags) == 0
            and count(f_insufficient, flags) > 0
        ):
            res["groups"].append("insufficient")
        elif (
            count(f_not(f_or(f_incompatible, f_timeout)), flags) == 0
            and count(f_incompatible, flags) > 0
        ):
            res["groups"].append("incompatible")
        elif (
            count(f_not(f_or(f_or(f_incompatible, f_insufficient), f_timeout)), flags)
            == 0
            and count(f_incompatible, flags) > 0
            and count(f_insufficient, flags) > 0
        ):
            res["groups"].append("insufficient")
            res["groups"].append("incompatible")
        else:
            res["groups"].append("uncategorized")

    # 我自己加的disagreement的判断
    if len(res["disagree_ledger_indexes"]) > 0:
        res["groups"].append("disagreement")
    return res


def get_validation_time(results):
    # 获取results["validation_times"]的平均值
    vt = []
    for r in results["validation_times"].values():
        # print(r) {seq: time, ...}
        vt += [t for t in r.values()]
    return sum(vt) / len(vt) if vt else None


def get_propose_set_message_count(results):
    # 获取results["TMProposeSet_messages"]的消息数量总和
    count = 0
    for proposes in results["TMProposeSet_messages"].values():
        # input(f"proposes: {proposes.keys()}")
        for keys, messages in proposes.items():
            # input(f"message count for {keys}: {len(messages)}")
            count += len(messages)
    return count


def get_validation_time_var(results):

    vars = []
    vt = results["validation_times"]
    # 获取所有seq
    seq = set()
    for r in vt.values():
        seq.update(r.keys())
    # input(f"all seq: {seq}")

    # 对每个seq，求所有node的validation time的方差
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


def get_validation_distribution_entropy(results):
    validation_distribution = results["validation_distribution"]
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


def aggregate_results(results, dir):
    results["avg_validation_time"] = get_validation_time(results)
    results["total_propose_set_messages"] = get_propose_set_message_count(results)
    results["num_getledger_hashes"] = len(results["requested_ledger_hashes"])
    results["num_getledger_messages"] = sum(
        len(msgs) for msgs in results["TMGetLedger_messages"].values()
    )
    results["validation_time_var"] = get_validation_time_var(results)
    results["validation_distribution_entropy"] = get_validation_distribution_entropy(results)

    return results


def get_getledger_hash_set(df_exec):
    requested_ledger_hashes = set()  # ledgerHash

    for _, row in df_exec.iterrows():
        message = row["message"]
        if row["message_type"] != "TMGetLedger":
            continue
        # input(f"message keys: {message.keys()}")
        if "ledgerHash" not in message:
            continue
        ledger_hash_value = message["ledgerHash"]
        if ledger_hash_value is None:
            print(f"Found None ledgerHash in TMGetLedger {message}, skipping.")
            continue
        ledger_hash = bytes(ledger_hash_value).hex()
        requested_ledger_hashes.add(ledger_hash)

    return requested_ledger_hashes


def get_getledger_messages(df_exec):
    getledger_messages = {}  # from, to -> {str(message) -> message json}

    for _, row in df_exec.iterrows():
        message = row["message"]
        if row["message_type"] != "TMGetLedger":
            continue
        from_node = row["from_node_id"]
        to_node = row["to_node_id"]
        if (from_node, to_node) not in getledger_messages:
            getledger_messages[(from_node, to_node)] = {}
        getledger_messages[(from_node, to_node)][str(message)] = message

    return getledger_messages


def get_propose_set(df_exec):
    # 返回一个字典
    # nodeid -> proposes
    # proposes也是一个字典，previousledger, proposeSeq, str(message) -> message json
    propose_set_messages = {}

    for _, row in df_exec.iterrows():
        message = row["message"]
        if row["message_type"] != "TMProposeSet":
            continue

        # nodePubKey 是原始字节数组
        nodepubkey_bytes = bytes(message["nodePubKey"])

        # 转换为 node_id
        node = pub_key_to_node_id(nodepubkey_bytes)

        if node is None:
            # 如果找不到匹配的 node_id，跳过
            continue

        if node not in propose_set_messages:
            propose_set_messages[node] = {}

        # previous_ledger 也是字节数组，转换为 hex 字符串
        previous_ledger = bytes(message["previousledger"]).hex()
        propose_seq = message["proposeSeq"]
        message_str = str(message)

        if (previous_ledger, propose_seq, message_str) not in propose_set_messages[
            node
        ]:
            propose_set_messages[node][
                (previous_ledger, propose_seq, message_str)
            ] = message

    # input(f"propose_set_messages: {propose_set_messages}")
    return propose_set_messages


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
def get_msg_sending_markov_matrix_similarity(df_exec):
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

    return mean_similarity


def get_validation_distribution(df_val):
    distribution = {}  # node_id -> {ledger_index -> {node_id: hash}}

    for _, row in df_val.iterrows():
        if row["validation_parsed"] is None:
            # 跳过拜占庭节点
            continue
            
        pubkey_hex = row["validation_parsed"]["SigningPubKey"]  # 十六进制字符串
        # 将十六进制字符串转换为 bytes
        pubkey_bytes = bytes.fromhex(pubkey_hex)
        sender_id = pub_key_to_node_id(pubkey_bytes)
        
        if sender_id is None:
            # 无法识别的公钥，跳过
            continue
        # input(f"sender_id: {sender_id}")
        for node in trusted_nodes.keys():
            if sender_id not in trusted_nodes[node]:
                continue
            ledger_index = row["validation_parsed"]["LedgerSequence"]
            ledger_hash_bytes = bytes.fromhex(row["validation_parsed"]["LedgerHash"])
            ledger_hash = ledger_hash_bytes.hex()
            if node not in distribution:
                distribution[node] = {}
            if ledger_index not in distribution[node]:
                distribution[node][ledger_index] = {}
            distribution[node][ledger_index][sender_id] = ledger_hash

        

    return distribution
    

def evaluate_test(dir):
    # print(f"Evaluating test in directory: {dir}")

    results = {
        "validation_times": {},
        "fully_validated_hashes": {},
        "disagree_ledger_indexes": [],
        "groups": ["all"],
        "TMProposeSet_messages": {},
        "requested_ledger_hashes": {},  # TMGetLedger消息中有多少ledgerHash
        "TMGetLedger_messages": {},
        "msg_entropy_integral": {},
        "msg_entropy_per_sec": {},
        "msg_sending_similarity": {},
        "validation_distribution": {},
    }

    execution_file = Path(dir) / "execution.csv"
    df_exec = pd.read_csv(execution_file)

    df_exec["message"] = df_exec["message"].apply(json.loads)

    results["TMProposeSet_messages"] = get_propose_set(df_exec)
    results["requested_ledger_hashes"] = get_getledger_hash_set(df_exec)
    results["TMGetLedger_messages"] = get_getledger_messages(df_exec)
    results["msg_entropy_integral"], results["msg_entropy_per_sec"] = (
        get_message_entropy_integration(df_exec)
    )
    results["msg_sending_similarity"] = get_msg_sending_markov_matrix_similarity(
        df_exec
    )

    df_exec_val = df_exec[df_exec["message_type"] == "TMValidation"].copy()
    df_exec_val["validation"] = df_exec_val["message"].apply(
        lambda x: bytes(x["validation"])
    )

    # 如果消息sender_node_id not in byzz_nodes，则解析validation_hex，在validation_parsed列中存储解析结果，否则存储None

    df_exec_val["validation_parsed"] = df_exec_val.apply(
        lambda row: (
            parse_bytes(bytes.fromhex(row["validation_hex"]))
            if row["from_node_id"] not in byzz_nodes
            else None
        ),
        axis=1,
    )
    results["validation_distribution"] = get_validation_distribution(df_exec_val)

    df_exec_sc = df_exec[df_exec["message_type"] == "TMStatusChange"].copy()
    df_exec_sc["newEvent"] = df_exec_sc["message"].apply(lambda x: x["newEvent"])
    df_exec_sc["ledgerSeq"] = df_exec_sc["message"].apply(lambda x: x["ledgerSeq"])

    for node_id in range(7):
        if node_id in byzz_nodes:
            continue
        file = Path(dir) / f"subscription_{node_id}.csv"
        df_subs = pd.read_csv(file)
        start = df_subs["timestamp"].min()
        end = df_subs["timestamp"].max()
        sec_elapsed = (end - start) / 1000.0
        # print(f"sec elapsed {sec_elapsed} sec")
        df_lgrClosed = df_subs[df_subs["message_type"] == "ledgerClosed"].copy()

        validation_times = get_validation_times(df_lgrClosed, df_exec_sc, node_id)
        results["validation_times"][node_id] = validation_times
        fully_validated_hashes = get_fully_validated_hashes(df_lgrClosed, node_id)
        results["fully_validated_hashes"][node_id] = fully_validated_hashes

    # 对所有的ledger_index，获取所有节点完全验证的这个index的ledger hash（如果有），如果不完全一样，将这个index加入disagree_ledger_indexes
    ledger_indexes = get_disagree_ledger_indexes(results["fully_validated_hashes"])
    results["disagree_ledger_indexes"] = ledger_indexes
    if len(ledger_indexes) > 0:
        input(f"Disagree ledger indexes: {ledger_indexes}")

    results = aggregate_results(results, dir)
    results = identify_violations(dir, results)
    return results


def get_base_dir():
    if len(sys.argv) == 2:
        latest_config = sys.argv[1]
        # 获取latest_config最后一层目录
        latest_config = latest_config
        return latest_config
    else:
        all_configs = sorted(os.listdir("traces"))
        if not all_configs:
            print("No directories found in 'traces'. Exiting.")
            exit(0)
        latest_config = all_configs[-1]
        return "traces/" + latest_config


def evaluate_all():
    base = get_base_dir()
    dirs = os.listdir(base)
    results = []

    # 测量总时间
    start_time = time()
    for dir in dirs:
        for dd in os.listdir(Path(base) / dir):
            res = evaluate_test(Path(base) / dir / dd)
            results.append(res)
    end_time = time()
    total_time = end_time - start_time
    print(f"Total time sequential: {total_time} seconds")
    return results


def render_results(
    grouped,
    groups=[
        "all",
        "correct",
        "insufficient",
        "incompatible",
        "timeout",
        "incomplete",
        "disagreement",
    ],
):
    from scipy.stats import mannwhitneyu

    def _get_aggregated_filed(grouped, filed):
        # 如果filed为"count"，则返回 len(grouped)
        if filed == "count":
            return str(len(grouped))
        vt_mean = []
        for res in grouped:
            vt = res.get(filed, None)
            if vt is not None:
                vt_mean.append(vt)
        # 返回 mean+-std的字符串形式
        if vt_mean:
            mean = np.mean(vt_mean)
            std = np.std(vt_mean)
            return f"{mean:.2f}" + r"$\pm$" + f"{std:.2f}"
        else:
            return "-"

    def _get_mann_whitney_u_test(grouped_correct, grouped_other, metric):
        """
        对比 grouped_other 与 grouped_correct 在 metric 上的差异
        返回 p-value 的字符串表示
        """
        # 提取 correct 组的数据
        correct_values = []
        for res in grouped_correct:
            val = res.get(metric, None)
            if val is not None:
                correct_values.append(val)
        
        # 提取 other 组的数据
        other_values = []
        for res in grouped_other:
            val = res.get(metric, None)
            if val is not None:
                other_values.append(val)
        
        # 如果任一组数据为空，返回 "-"
        if len(correct_values) == 0 or len(other_values) == 0:
            print(f"One of the groups for metric {metric} is empty. Skipping Mann-Whitney U test.")
            return "-"
        
        # 如果任一组数据少于2个样本，无法进行检验
        if len(correct_values) < 2 or len(other_values) < 2:
            print(f"One of the groups for metric {metric} has less than 2 samples. Skipping Mann-Whitney U test.")
            return "-"
        
        # 执行 Mann-Whitney U 检验
        try:
            statistic, p_value = mannwhitneyu(correct_values, other_values, alternative='two-sided')
            # 格式化 p-value
            if p_value < 0.001:
                # 科学计数法
                return f"${p_value:.2e}$"
            else:
                return f"${p_value:.3f}$"
        except Exception as e:
            # 如果检验失败，返回错误标记
            return "err"

    def render_row(grouped, groups, f, metric, label):
        print(
            label
            + " & "
            + " & ".join([_get_aggregated_filed(grouped[g], metric) for g in groups])
            + r" \\",
            file=f,
        )
    
    def render_stats_row(grouped, groups, f, metric, label):
        """渲染统计检验行，与 correct 组比较"""
        cells = []
        for g in groups:
            if g == "correct":
                # correct 组自己与自己比较，显示 "-"
                cells.append("-")
            elif g == "all":
                cells.append("-")
            else:
                # 其他组与 correct 组比较
                p_val_str = _get_mann_whitney_u_test(grouped["correct"], grouped[g], metric)
                cells.append(p_val_str)
        
        print(
            label + " & " + " & ".join(cells) + r" \\",
            file=f,
        )

    # 生成 table.tex（统计值）
    with open("out/table.tex", "w") as f:
        print(r"\begin{table}[ht]", file=f)
        print(r"\centering", file=f)
        print(r"\resizebox{\linewidth}{!}{%", file=f)
        print(r"\begin{tabular}{" + ("l" + "c" * len(groups)) + "}", file=f)
        print(r"\toprule", file=f)
        print("& " + " & ".join(groups) + r" \\", file=f)
        print(r"\hline", file=f)
        render_row(grouped, groups, f, "count", r"\# tests")
        render_row(grouped, groups, f, "avg_validation_time", r"Val Time mean (s)")
        render_row(grouped, groups, f, "validation_time_var", r"Val Time by seq variance mean")
        render_row(grouped, groups, f, "total_propose_set_messages", r"\# TMProposeSet")
        render_row(grouped, groups, f, "num_getledger_hashes", r"\# TMGetLedger Hashes")
        render_row(grouped, groups, f, "num_getledger_messages", r"\# TMGetLedger Msgs")
        render_row(
            grouped,
            groups,
            f,
            "msg_entropy_integral",
            r"Msg Entropy Integral (dt=0.1s)",
        )
        render_row(
            grouped, groups, f, "msg_entropy_per_sec", r"Msg Entropy / Sec (dt=0.1s)"
        )
        render_row(
            grouped, groups, f, "msg_sending_similarity", r"Msg Sending Similarity"
        )
        render_row(
            grouped, groups, f, "validation_distribution_entropy", r"Val Distribution Entropy mean"
        )

        print(r"\bottomrule", file=f)
        print(r"\end{tabular}%", file=f)
        print(r"}", file=f)
        print(r"\end{table}", file=f)

    print(f"generated out/table.tex")
    
    # 生成 stats.tex（Mann-Whitney U 检验 p-values）
    with open("out/stats.tex", "w") as f:
        print(r"\begin{table}[ht]", file=f)
        print(r"\centering", file=f)
        print(r"\resizebox{\linewidth}{!}{%", file=f)
        print(r"\begin{tabular}{" + ("l" + "c" * len(groups)) + "}", file=f)
        print(r"\toprule", file=f)
        print("& " + " & ".join(groups) + r" \\", file=f)
        print(r"\hline", file=f)
        render_stats_row(grouped, groups, f, "count", r"\# tests")
        render_stats_row(grouped, groups, f, "avg_validation_time", r"Val Time mean (s)")
        render_stats_row(grouped, groups, f, "validation_time_var", r"Val Time by seq variance mean")
        render_stats_row(grouped, groups, f, "total_propose_set_messages", r"\# TMProposeSet")
        render_stats_row(grouped, groups, f, "num_getledger_hashes", r"\# TMGetLedger Hashes")
        render_stats_row(grouped, groups, f, "num_getledger_messages", r"\# TMGetLedger Msgs")
        render_stats_row(
            grouped,
            groups,
            f,
            "msg_entropy_integral",
            r"Msg Entropy Integral (dt=0.1s)",
        )
        render_stats_row(
            grouped, groups, f, "msg_entropy_per_sec", r"Msg Entropy / Sec (dt=0.1s)"
        )
        render_stats_row(
            grouped, groups, f, "msg_sending_similarity", r"Msg Sending Similarity"
        )
        render_stats_row(
            grouped, groups, f, "validation_distribution_entropy", r"Val Distribution Entropy mean"
        )

        print(r"\bottomrule", file=f)
        print(r"\end{tabular}%", file=f)
        print(r"}", file=f)
        print(r"\end{table}", file=f)

    print(f"generated out/stats.tex")


def group_results(
    results,
    groups=[
        "all",
        "correct",
        "insufficient",
        "incompatible",
        "timeout",
        "incomplete",
        "disagreement",
    ],
):
    grouped = {g: [] for g in groups}
    for res in results:
        for g in groups:
            if g in res["groups"]:
                grouped[g].append(res)
    return grouped


def main():

    res1 = evaluate_all()
    grouped = group_results(res1)
    render_results(grouped)


if __name__ == "__main__":
    main()
