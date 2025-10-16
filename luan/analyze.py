import os
import re
from types import NoneType
import pandas as  pd
import sys
import argparse

parser = argparse.ArgumentParser(description="Analyze Lua files in a directory.")
parser.add_argument("dir", type=str, help="Path to the directory containing Lua files")
args = parser.parse_args()


def extract_ledger_hash_seq(df):
    # 批量处理DataFrame每一行，返回[(from_node_id, ledger_seq, ledger_hash_hex), ...]
    results = []
    for _, row in df.iterrows():
        raw = row["original_data"]
        h_match = re.search(r'ledgerHash: "([^"]+)"', str(raw))
        if h_match:
            try:
                h_bytes = h_match.group(1).encode("latin1").decode("unicode_escape").encode("latin1")
                h_hex = h_bytes.hex().upper()
            except Exception as e:
                h_hex = None
        else:
            h_hex = None
        seq_match = re.search(r'ledgerSeq: (\d+);', str(raw))
        if seq_match:
            seq = int(seq_match.group(1))
        else:
            seq = None
        from_node = row["from_node_id"] if "from_node_id" in row else None
        results.append((from_node, seq, h_hex))
    return results

def analyze_ledger_seq(df):
    df_status = df[df["message_type"] == "TMStatusChange"]
    results = extract_ledger_hash_seq(df_status)
    # 按node分组，seq升序排序
    from collections import defaultdict
    node_map = defaultdict(list)
    for from_node, seq, h in results:
        if from_node is not None and seq is not None and h is not None:
            node_map[from_node].append((seq, h))

    for node in sorted(node_map.keys(), key=lambda x: int(x)):
        seq_hash_dict = defaultdict(set)
        for seq, h in node_map[node]:
            seq_hash_dict[seq].add(h)
        print(f"node {node}:")
        for seq in sorted(seq_hash_dict.keys()):
            hashes = seq_hash_dict[seq]
            if len(hashes) > 1:
                print(f"  WARNING: node {node} ledger seq {seq} has multiple hashes: {sorted(hashes)}")
            # 只输出第一个hash（或全部hash，按需）
            print(f"  ledger seq {seq}: {sorted(hashes)[0]}")

def analyze_validation(df):

    df_val = df[df["message_type"] == "TMValidation"]


    import codecs
    from collections import defaultdict


    # Ripple SField type+code映射表（常用字段，部分）
    SFIELDS = {
        0x20: ("sfFlags", 4),
        0x22: ("sfCloseTime", 4),
        0x26: ("sfLedgerSequence", 4),
        0x51: ("sfLedgerHash", 32),
        0x73: ("sfSigningPubKey", None), # 变长
        0x74: ("sfTxnSignature", None),  # 变长
        0x1B: ("sfLedgerSequence", 4),
        0x10: ("sfFlags", 4),
        0x14: ("sfLedgerHash", 32),
        0x30: ("sfSigningPubKey", None),
        0x31: ("sfTxnSignature", None),
        0x3F: ("sfValidationPublicKey", None),
        0x72: ("sfSignature", None),
        0x75: ("sfTxnSignature", None),
        0x77: ("sfValidationPublicKey", None),
        0xF1: ("sfIndex", 32),
        # 其他常见字段可继续补充...
    }

    def parse_stobject(data: bytes):
        # TLV解析，返回字段名:十六进制
        i = 0
        fields = {}
        while i < len(data):
            tag = data[i]
            i += 1
            if tag == 0xE1:  # Object end
                break
            if tag in SFIELDS:
                name, flen = SFIELDS[tag]
                if flen is not None:
                    val = data[i:i+flen]
                    fields[name] = val.hex().upper()
                    i += flen
                else:
                    # 变长字段，前1字节为长度
                    vlen = data[i]
                    i += 1
                    val = data[i:i+vlen]
                    fields[name] = val.hex().upper()
                    i += vlen
            else:
                # 未知tag，尝试跳过1字节
                fields[f"unknown_{tag:02X}"] = data[i:i+1].hex().upper()
                i += 1
        return fields

    node_map = defaultdict(list)

    for _, row in df[df["message_type"] == "TMValidation"].iterrows():
        from_node = row["from_node_id"] if "from_node_id" in row else None
        raw = row["original_data"]
        v_match = re.search(r'validation: "+(.*?)"+;?', str(raw), re.DOTALL)
        v_str = v_match.group(1) if v_match else None
        fields = None
        if v_str:
            try:
                v_bytes = codecs.decode(v_str, 'unicode_escape').encode('latin1')
                fields = parse_stobject(v_bytes)
            except Exception as e:
                fields = {"PARSE_ERROR": str(e)}
        node_map[from_node].append((fields, v_str))

    for node in sorted(node_map.keys(), key=lambda x: int(x) if x is not None else -1):
        print(f"node {node}:")
        for fields, v_str in node_map[node]:
            print("  fields:")
            for k, v in (fields.items() if fields else []):
                print(f"    {k}: {v}")
            print(f"  validation_raw=\n{v_str}\n")

def analyze_iteration(iteration_dir):
    print(f"Analyzing {iteration_dir}...")
    # 获取 action-i.csv 文件，i是和iteration-i对应的数字
    iteration_num = iteration_dir.split("-")[1]
    action_file = os.path.join(args.dir, iteration_dir, f"action-{iteration_num}.csv")
    if not os.path.isfile(action_file):
        print(f"Warning: {action_file} not found, skipping.")
        return

    df = pd.read_csv(action_file)
    # analyze_ledger_seq(df)
    analyze_validation(df)


def main():
    
    # 用户从命令行传入一个文件夹路径
    print(f"Analyzing : {args.dir}")
    
    # 找到这个文件夹下所有的 iteration-i 的文件夹，并根据i排序
    iteration_dirs = sorted([d for d in os.listdir(args.dir) if d.startswith("iteration-") and os.path.isdir(os.path.join(args.dir, d))], key=lambda x: int(x.split("-")[1]))
    print(f"Found iteration directories: {iteration_dirs}")

   # 逐个分析每个 iteration-i 文件夹
    for iteration_dir in iteration_dirs:
        analyze_iteration(iteration_dir)
        
        
        




if __name__ == "__main__":
    main()
