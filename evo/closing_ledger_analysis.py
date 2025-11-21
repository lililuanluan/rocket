import json
import pandas as pd
import sys
from pathlib import Path
import math

# Ensure project root is on sys.path so `protos` and other top-level packages import correctly
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def MessageToDict(msg, **kwargs):
    return {"raw_proto": str(msg)}

from protos import packet_pb2, ripple_pb2
from rocket_controller.encoder_decoder import PacketEncoderDecoder, DecodingNotSupportedError

def _get_message(hex):
    raw = bytes.fromhex(hex)    
    pkt = packet_pb2.Packet()
    pkt.data = raw
    message, message_type = PacketEncoderDecoder.decode_packet(pkt)
    return message

def _parse_row(row):
    hex_str = row.get("packet_data")
    if not isinstance(hex_str, str) or len(hex_str) == 0:
        return {"error": "empty packet_data"}

    # Clean common prefixes/spaces
    clean = hex_str.strip()
    message = _get_message(clean)


    # print((message.newEvent == ripple_pb2.neCLOSING_LEDGER))
    # print(f"node {row['from_node_id']} seq {message.ledgerSeq}, hash {message.ledgerHash.hex()}")
    return message


def analyze_closing_ledger(action_file, max_seq=math.inf):
    # 一个表格，(nodeid, ledger_seq) -> set(ledger_hash)
    ledger_map = {}
    df = pd.read_csv(action_file)
    # filter to status change messages as before
    df = df[df["message_type"] == "TMStatusChange"]

    
    for _, row in df.iterrows():
        message = _parse_row(row)
        if message.ledgerSeq > max_seq:
            continue
        key = (row["from_node_id"], message.ledgerSeq)
        ledger_hash = message.ledgerHash.hex()
        if key not in ledger_map:
            ledger_map[key] = set()
        ledger_map[key].add(ledger_hash)

    for v in ledger_map.values():
        assert len(v) == 1
    return ledger_map

def render_table(ledger_map, action_file=None):
    """Render ledger_map into a LaTeX table file.

    ledger_map: dict with keys (node_id, ledger_seq) -> set of hex-hash strings
    action_file: optional path to the action CSV used to derive run name (e.g. G0T1)
    The output file will be written to an `out` directory next to this script as
    `<run>_validation_hash.tex` (or `validation_hash.tex` if run name not found).
    """
    # prepare output directory
    out_dir = Path(__file__).resolve().parent / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    # derive run name from action_file path if possible
    run_name = None
    if action_file:
        try:
            p = Path(action_file)
            # expecting .../<GxTy>/iteration-1/action-1.csv
            if p.parents and len(p.parents) >= 2:
                run_name = p.parents[1].name
        except Exception:
            run_name = None

    filename = f"{run_name + '_' if run_name else ''}validation_hash.tex"
    out_path = out_dir / filename

    node_ids = sorted(set(k[0] for k in ledger_map.keys()))
    ledger_seqs = sorted(set(k[1] for k in ledger_map.keys()))

    # helper to render cell: join multiple hashes with comma, truncate to 5 chars
    def render_cell(hset):
        if not hset:
            return "-"
        parts = []
        for h in sorted(hset):
            # ensure hex string
            hh = h.lower()
            parts.append(hh[:5])
        return ", ".join(parts)

    with open(out_path, "w") as f:
        print(r"\begin{table}[ht]", file=f)
        print(r"\centering", file=f)
        col_spec = "l" + "c" * len(node_ids)
        print(r"\begin{tabular}{" + col_spec + "}", file=f)
        print(r"\toprule", file=f)

        # header
        print("Ledger Seq", end="", file=f)
        for node_id in node_ids:
            print(f" & Node {node_id}", end="", file=f)
        print(r" \\", file=f)
        print(r"\hline", file=f)

        # rows
        for seq in ledger_seqs:
            print(f"{seq}", end="", file=f)
            for node_id in node_ids:
                cell = render_cell(ledger_map.get((node_id, seq), set()))
                print(f" & {cell}", end="", file=f)
            print(r" \\", file=f)

        print(r"\bottomrule", file=f)
        print(r"\end{tabular}", file=f)
        if run_name:
            print(r"\caption{Validation hashes for " + run_name + "}", file=f)
        print(r"\end{table}", file=f)

    print(f"Wrote validation hash table to {out_path}")


if __name__ == "__main__":
    max_seq = 15
    action_file = "/Users/lli21/rocket/logs/2025_11_21_13h58m/G0T1/iteration-1/action-1.csv"
    table = analyze_closing_ledger(action_file, max_seq=max_seq)
    
    render_table(table, action_file)