from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any


VALIDATOR_DEBUG_RE = re.compile(r"validator_(\d+)_debug\.txt$")
VALIDATOR_LOG_RE = re.compile(r"validator_(\d+)_log\.txt$")
TRIE_RE = re.compile(r"ValidationTrie (\{.*\})$")
TIMESTAMP_RE = re.compile(
    r"^(\d{4}-[A-Za-z]{3}-\d{2} \d{2}:\d{2}:\d{2}\.\d+ UTC)\s"
)
BUILT_LEDGER_RE = re.compile(r"Built ledger #(\d+): ([A-F0-9]+)")
ON_ACCEPT_RE = re.compile(
    r"onAccept: .*previous ledgerID: ([A-F0-9]+), seq: (\d+)\."
)
CONSENSUS_TIME_RE = re.compile(r"Consensus time for #(\d+) with LCL ([A-F0-9]+)")
OUR_LCL_RE = re.compile(r"Our LCL: ([A-F0-9]+)")
NET_LCL_RE = re.compile(r"Net LCL ([A-F0-9]+)")
SPAN_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\)$")


def _resolve_validator_log_dir(log_dir: str | Path) -> Path:
    path = Path(log_dir).expanduser().resolve()

    if path.is_file():
        if VALIDATOR_DEBUG_RE.fullmatch(path.name) or VALIDATOR_LOG_RE.fullmatch(path.name):
            return path.parent
        raise FileNotFoundError(f"Unsupported file input: {path}")

    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")

    if any(path.glob("validator_*_debug.txt")) or any(path.glob("validator_*_log.txt")):
        return path

    iteration_live_logs = path / "iteration-1" / "validator_live_logs"
    if iteration_live_logs.is_dir():
        return iteration_live_logs

    live_logs = path / "validator_live_logs"
    if live_logs.is_dir():
        return live_logs

    raise FileNotFoundError(
        "Could not find validator debug logs under "
        f"{path}. Expected validator_*_debug.txt, validator_*_log.txt, "
        "or iteration-1/validator_live_logs/"
    )


def _search_backward(
    lines: list[str], start_idx: int, pattern: re.Pattern[str], max_lines: int = 40
) -> re.Match[str] | None:
    lower = max(0, start_idx - max_lines)
    for idx in range(start_idx - 1, lower - 1, -1):
        match = pattern.search(lines[idx])
        if match:
            return match
    return None


def _search_forward(
    lines: list[str], start_idx: int, pattern: re.Pattern[str], max_lines: int = 80
) -> re.Match[str] | None:
    upper = min(len(lines), start_idx + max_lines + 1)
    for idx in range(start_idx + 1, upper):
        if "ValidationTrie" in lines[idx]:
            break
        match = pattern.search(lines[idx])
        if match:
            return match
    return None


def _extract_timestamp(line: str) -> str | None:
    match = TIMESTAMP_RE.match(line)
    return match.group(1) if match else None


def _timestamp_tail(timestamp: str | None) -> str | None:
    if not timestamp:
        return None
    match = re.search(r" (\d{2}:\d{2}:\d{2})\.", timestamp)
    if match:
        return match.group(1)
    try:
        dt = datetime.strptime(timestamp, "%Y-%b-%d %H:%M:%S UTC")
        return dt.strftime("%H:%M:%S")
    except ValueError:
        return timestamp


def _parse_validator_file(log_path: Path) -> dict[int, dict[str, Any]]:
    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    snapshots: dict[int, dict[str, Any]] = {}

    for idx, line in enumerate(lines):
        trie_match = TRIE_RE.search(line)
        if not trie_match:
            continue

        trie_json = json.loads(trie_match.group(1))

        built_match = _search_backward(lines, idx, BUILT_LEDGER_RE)
        on_accept_match = _search_forward(lines, idx, ON_ACCEPT_RE)
        consensus_match = _search_forward(lines, idx, CONSENSUS_TIME_RE)
        our_lcl_match = _search_forward(lines, idx, OUR_LCL_RE)
        net_lcl_match = _search_forward(lines, idx, NET_LCL_RE)

        built_seq = int(built_match.group(1)) if built_match else None
        built_hash = built_match.group(2) if built_match else None

        next_prev_seq = int(on_accept_match.group(2)) if on_accept_match else None
        next_prev_hash = on_accept_match.group(1) if on_accept_match else None

        next_consensus_seq = (
            int(consensus_match.group(1)) if consensus_match else None
        )
        next_consensus_lcl = consensus_match.group(2) if consensus_match else None

        round_seq = built_seq
        if round_seq is None:
            round_seq = next_prev_seq
        if round_seq is None and next_consensus_seq is not None:
            round_seq = next_consensus_seq - 1

        if round_seq is None:
            seq_support = trie_json.get("seq_support", {})
            if seq_support:
                round_seq = max(int(seq) for seq in seq_support.keys())

        if round_seq is None:
            raise ValueError(
                f"Could not infer round sequence for trie at {log_path}:{idx + 1}"
            )

        snapshot = {
            "line_no": idx + 1,
            "timestamp": _extract_timestamp(line),
            "round_seq": round_seq,
            "built_ledger_seq": built_seq,
            "built_ledger_hash": built_hash,
            "next_round_prev_seq": next_prev_seq,
            "next_round_prev_hash": next_prev_hash,
            "next_round_consensus_seq": next_consensus_seq,
            "next_round_consensus_lcl": next_consensus_lcl,
            "our_lcl": our_lcl_match.group(1) if our_lcl_match else None,
            "net_lcl": net_lcl_match.group(1) if net_lcl_match else None,
            "trie": trie_json,
        }

        existing = snapshots.get(round_seq)
        if existing is None:
            snapshots[round_seq] = snapshot
            continue

        duplicates = existing.setdefault("duplicates", [])
        duplicates.append(snapshot)

    return snapshots


def parse_trie(log_dir: str | Path) -> dict[int, dict[int, dict[str, Any]]]:
    """
    Parse per-node ValidationTrie snapshots printed at the end of consensus rounds.

    The input may be:
    - a saved run directory such as .../G258T3
    - an iteration directory such as .../G258T3/iteration-1
    - a validator_live_logs directory
    - one validator_*_debug.txt file

    Returns:
        {
            node_id: {
                round_seq: {
                    "timestamp": "...",
                    "line_no": 123,
                    "round_seq": 6,
                    "built_ledger_seq": 6,
                    "built_ledger_hash": "...",
                    "next_round_prev_seq": 6,
                    "next_round_prev_hash": "...",
                    "next_round_consensus_seq": 7,
                    "next_round_consensus_lcl": "...",
                    "our_lcl": "...",
                    "net_lcl": "...",
                    "trie": {... parsed ValidationTrie json ...},
                }
            }
        }
    """

    validator_log_dir = _resolve_validator_log_dir(log_dir)
    parsed: dict[int, dict[int, dict[str, Any]]] = {}

    node_to_files: dict[int, dict[str, Path]] = {}
    for log_path in sorted(validator_log_dir.glob("validator_*_debug.txt")):
        match = VALIDATOR_DEBUG_RE.fullmatch(log_path.name)
        if not match:
            continue
        node_to_files.setdefault(int(match.group(1)), {})["debug"] = log_path

    for log_path in sorted(validator_log_dir.glob("validator_*_log.txt")):
        match = VALIDATOR_LOG_RE.fullmatch(log_path.name)
        if not match:
            continue
        node_to_files.setdefault(int(match.group(1)), {})["log"] = log_path

    for node_id in sorted(node_to_files):
        files = node_to_files[node_id]
        snapshots: dict[int, dict[str, Any]] = {}

        debug_path = files.get("debug")
        if debug_path is not None:
            snapshots = _parse_validator_file(debug_path)

        # Some runs keep ValidationTrie lines only in validator_*_log.txt while
        # the companion debug file is empty or nearly empty.
        if not snapshots:
            log_path = files.get("log")
            if log_path is not None:
                snapshots = _parse_validator_file(log_path)

        parsed[node_id] = snapshots

    if not parsed:
        raise FileNotFoundError(
            "No validator_*_debug.txt or validator_*_log.txt files found under "
            f"{validator_log_dir}"
        )

    return parsed


def _resolve_current_ledger_hash(snapshot: dict[str, Any]) -> str | None:
    return (
        snapshot.get("our_lcl")
        or snapshot.get("built_ledger_hash")
        or snapshot.get("next_round_prev_hash")
    )


def _find_ledger_seq_in_trie(
    trie_root: dict[str, Any], ledger_hash: str | None
) -> int | None:
    if not ledger_hash:
        return None

    target_hash = ledger_hash.upper()
    for node in _walk_trie_nodes(trie_root):
        start_id = str(node.get("startID", "")).upper()
        tip_hash = _node_tip_hash(node).upper()

        if target_hash == tip_hash:
            return _node_tip_seq(node)

        if target_hash == start_id:
            start_seq, _ = _node_span_bounds(node)
            if start_seq is not None:
                return start_seq
            return _node_tip_seq(node)

    return None


def _resolve_current_ledger_seq(snapshot: dict[str, Any]) -> int | None:
    trie_root = snapshot.get("trie", {}).get("trie")
    if isinstance(trie_root, dict):
        current_hash = _resolve_current_ledger_hash(snapshot)
        ledger_seq = _find_ledger_seq_in_trie(trie_root, current_hash)
        if ledger_seq is not None:
            return ledger_seq

    for field in ("built_ledger_seq", "round_seq", "next_round_prev_seq"):
        value = snapshot.get(field)
        try:
            return int(value)
        except (TypeError, ValueError):
            continue

    return None


def get_snapshot_tip_distance(snapshot: dict[str, Any]) -> int | None:
    trie_root = snapshot.get("trie", {}).get("trie")
    if not isinstance(trie_root, dict):
        return None

    tip_seqs = [
        tip_seq
        for tip_seq in (_node_tip_seq(node) for node in _walk_trie_nodes(trie_root))
        if tip_seq is not None
    ]
    if not tip_seqs:
        return None

    current_seq = _resolve_current_ledger_seq(snapshot)
    if current_seq is None:
        return None

    return max(0, max(tip_seqs) - current_seq)


def get_tip_distance_sums_by_seq(
    parsed: dict[int, dict[int, dict[str, Any]]],
) -> dict[int, int]:
    seq_to_total_distance: dict[int, int] = {}

    for seq in sorted({seq for node_map in parsed.values() for seq in node_map}):
        total_distance = 0
        found_snapshot = False

        for node_snapshots in parsed.values():
            snapshot = node_snapshots.get(seq)
            if snapshot is None:
                continue

            distance = get_snapshot_tip_distance(snapshot)
            if distance is None:
                continue

            total_distance += distance
            found_snapshot = True

        if found_snapshot:
            seq_to_total_distance[seq] = total_distance

    return seq_to_total_distance


def get_max_tip_distance(
    parsed_or_log_dir: dict[int, dict[int, dict[str, Any]]] | str | Path,
) -> int | None:
    """Return the maximum summed tip-distance across all observed sequences."""
    if isinstance(parsed_or_log_dir, (str, Path)):
        parsed = parse_trie(parsed_or_log_dir)
    else:
        parsed = parsed_or_log_dir

    seq_to_total_distance = get_tip_distance_sums_by_seq(parsed)
    if not seq_to_total_distance:
        return None

    return max(seq_to_total_distance.values())


def get_sum_tip_distance(
    parsed_or_log_dir: dict[int, dict[int, dict[str, Any]]] | str | Path,
) -> int | None:
    """Return the total summed tip-distance across all observed sequences."""
    if isinstance(parsed_or_log_dir, (str, Path)):
        parsed = parse_trie(parsed_or_log_dir)
    else:
        parsed = parsed_or_log_dir

    seq_to_total_distance = get_tip_distance_sums_by_seq(parsed)
    if not seq_to_total_distance:
        return None

    return sum(seq_to_total_distance.values())


def _node_hash_prefix(node: dict[str, Any]) -> str:
    start_id = str(node.get("startID", ""))
    if start_id:
        return start_id[:8]

    span = str(node.get("span", ""))
    return span.split("[", 1)[0][:8]


def _node_tip_hash(node: dict[str, Any]) -> str:
    span = str(node.get("span", ""))
    return span.split("[", 1)[0]


def _node_span_bounds(node: dict[str, Any]) -> tuple[int | None, int | None]:
    span = str(node.get("span", ""))
    match = SPAN_BOUNDS_RE.search(span)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


def _node_tip_seq(node: dict[str, Any]) -> int | None:
    seq = node.get("seq")
    try:
        return int(seq)
    except (TypeError, ValueError):
        _, span_end = _node_span_bounds(node)
        if span_end is None:
            return None
        return span_end - 1


def _walk_trie_nodes(node: dict[str, Any]):
    yield node
    for child in node.get("children", []):
        yield from _walk_trie_nodes(child)


def _node_matches_ledger(node: dict[str, Any], ledger_hash: str | None) -> bool:
    if not ledger_hash:
        return False

    start_id = str(node.get("startID", ""))
    tip_hash = _node_tip_hash(node)
    return ledger_hash == start_id or ledger_hash == tip_hash


def _forest_label(node: dict[str, Any]) -> str:
    seq = node.get("seq", "?")
    tip = node.get("tipSupport", "?")
    branch = node.get("branchSupport", "?")
    hash_prefix = _node_hash_prefix(node) or "????????"
    return f"s{seq}\\\\{hash_prefix}\\\\t{tip}/b{branch}"


def _forest_style_suffix(node: dict[str, Any], snapshot: dict[str, Any]) -> str:
    current_local_lcl = snapshot.get("our_lcl")
    next_round_lcl = snapshot.get("next_round_consensus_lcl") or snapshot.get("net_lcl")

    is_current = _node_matches_ledger(node, current_local_lcl)
    is_next_round = _node_matches_ledger(node, next_round_lcl)

    # The user wants only two colors:
    # - green for the next-round chosen ledger
    # - red for the current local ledger only when it differs from next round
    if is_next_round:
        return ", next round ledger"
    if is_current and current_local_lcl != next_round_lcl:
        return ", current local ledger"
    return ""


def _trie_to_forest(node: dict[str, Any], snapshot: dict[str, Any]) -> str:
    label = _forest_label(node)
    style_suffix = _forest_style_suffix(node, snapshot)
    children = node.get("children", [])

    if not children:
        return f"[{{{label}}}{style_suffix}]"

    rendered_children = " ".join(_trie_to_forest(child, snapshot) for child in children)
    return f"[{{{label}}}{style_suffix} {rendered_children}]"


def _snapshot_metadata_lines(snapshot: dict[str, Any]) -> list[str]:
    lines: list[str] = []

    built_hash = snapshot.get("built_ledger_hash")
    if built_hash:
        lines.append(f"Built ledger = {built_hash[:8]}")

    our_lcl = snapshot.get("our_lcl")
    if our_lcl:
        lines.append(f"Current local last closed ledger = {our_lcl[:8]}")

    net_lcl = snapshot.get("net_lcl")
    if net_lcl:
        lines.append(f"Network preferred last closed ledger = {net_lcl[:8]}")

    next_round_lcl = snapshot.get("next_round_consensus_lcl")
    if next_round_lcl:
        lines.append(f"Next round chosen last closed ledger = {next_round_lcl[:8]}")

    ts = _timestamp_tail(snapshot.get("timestamp"))
    if ts:
        lines.append(f"Trie log time = {ts}")

    duplicates = snapshot.get("duplicates", [])
    if duplicates:
        lines.append(f"Duplicate trie snapshots = {1 + len(duplicates)}")

    return lines


def _snapshot_to_tex(snapshot: dict[str, Any]) -> str:
    trie = snapshot["trie"]["trie"]
    forest_body = _trie_to_forest(trie, snapshot)
    metadata_lines = _snapshot_metadata_lines(snapshot)

    parts = [r"\begin{minipage}[t]{\linewidth}", r"\centering"]
    for meta in metadata_lines:
        parts.append(r"{\tiny\texttt{" + meta + r"}}\par")

    if metadata_lines:
        parts.append(r"\vspace{0.5mm}")

    parts.extend(
        [
            r"\begin{forest}",
            r"preferred trie,",
            forest_body,
            r"\end{forest}",
            r"\end{minipage}",
        ]
    )
    return "\n".join(parts)


def _select_sequences(
    parsed: dict[int, dict[int, dict[str, Any]]],
    seq_from: int | None = None,
    seq_to: int | None = None,
) -> list[int]:
    seqs = sorted({seq for node_map in parsed.values() for seq in node_map})
    if seq_from is not None:
        seqs = [seq for seq in seqs if seq >= seq_from]
    if seq_to is not None:
        seqs = [seq for seq in seqs if seq <= seq_to]
    return seqs


def write_trie_table_tex(
    parsed: dict[int, dict[int, dict[str, Any]]],
    out_path: str | Path,
    seq_from: int | None = None,
    seq_to: int | None = None,
    caption: str = "ValidationTrie snapshots by node and consensus round",
    label: str = "tab:preferred-trie",
) -> Path:
    out = Path(out_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    node_ids = sorted(parsed)
    seqs = _select_sequences(parsed, seq_from=seq_from, seq_to=seq_to)

    if not node_ids:
        raise ValueError("No parsed nodes available")
    if not seqs:
        raise ValueError("No sequences available for the requested range")

    seq_col_width_cm = 1.1
    cell_width_cm = 5.0
    margin_cm = 0.6
    tabcolsep_pt = 2.0
    pt_to_cm = 0.03514598
    total_cols = 1 + len(node_ids)
    tabcolsep_total_cm = 2.0 * total_cols * tabcolsep_pt * pt_to_cm
    table_width_cm = seq_col_width_cm + len(node_ids) * cell_width_cm + tabcolsep_total_cm
    paper_width_cm = table_width_cm + 2.0 * margin_cm + 0.05
    paper_height_cm = 29.7

    col_spec = (
        r">{\centering\arraybackslash}p{"
        + f"{seq_col_width_cm:.2f}cm"
        + "}"
        + "".join(
            r">{\centering\arraybackslash}p{" + f"{cell_width_cm:.2f}cm" + "}"
            for _ in node_ids
        )
    )

    lines = [
        r"\documentclass[10pt]{article}",
        r"\usepackage[paperwidth="
        + f"{paper_width_cm:.2f}cm"
        + r",paperheight="
        + f"{paper_height_cm:.2f}cm"
        + r",margin="
        + f"{margin_cm:.2f}cm"
        + r"]{geometry}",
        r"\usepackage{array}",
        r"\usepackage{booktabs}",
        r"\usepackage{longtable}",
        r"\usepackage{forest}",
        r"\pagestyle{plain}",
        r"\setlength{\tabcolsep}{" + f"{tabcolsep_pt:.1f}pt" + r"}",
        r"\setlength{\LTleft}{0pt}",
        r"\setlength{\LTright}{0pt}",
        r"\renewcommand{\arraystretch}{1.15}",
        r"\forestset{",
        r"  preferred trie/.style={",
        r"    for tree={",
        r"      draw,",
        r"      rounded corners,",
        r"      align=center,",
        r"      font=\tiny\ttfamily,",
        r"      inner sep=1pt,",
        r"      l sep=2mm,",
        r"      s sep=1.2mm,",
        r"      anchor=north,",
        r"    }",
        r"  },",
        r"  current local ledger/.style={",
        r"    draw=red!75!black,",
        r"    fill=red!10,",
        r"    line width=0.9pt,",
        r"  },",
        r"  next round ledger/.style={",
        r"    draw=green!50!black,",
        r"    fill=green!10,",
        r"    line width=0.9pt,",
        r"  }",
        r"}",
        r"\begin{document}",
        r"\small",
        r"\noindent\textbf{Legend: }",
        r"\fcolorbox{red!75!black}{red!10}{\rule{0pt}{1.2ex}\hspace{1.8ex}}"
        r" current local last closed ledger when it differs from next round\quad",
        r"\fcolorbox{green!50!black}{green!10}{\rule{0pt}{1.2ex}\hspace{1.8ex}}"
        r" next round chosen last closed ledger",
        r"\par\vspace{1mm}",
        r"\begin{longtable}{" + col_spec + "}",
        r"\caption{" + caption + r"}\label{" + label + r"}\\",
        r"\toprule",
        "Seq & " + " & ".join(f"Node {node_id}" for node_id in node_ids) + r"\\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        "Seq & " + " & ".join(f"Node {node_id}" for node_id in node_ids) + r"\\",
        r"\midrule",
        r"\endhead",
        r"\bottomrule",
        r"\endfoot",
    ]

    for seq in seqs:
        row = [str(seq)]
        for node_id in node_ids:
            snapshot = parsed[node_id].get(seq)
            if snapshot is None:
                row.append(r"{\large --}")
            else:
                row.append(_snapshot_to_tex(snapshot))
        lines.append(" & ".join(row) + r"\\")
        lines.append(r"\midrule")

    lines.extend(
        [
            r"\end{longtable}",
            r"\end{document}",
        ]
    )

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse ValidationTrie snapshots from validator debug logs."
    )
    parser.add_argument(
        "log_dir",
        nargs="?",
        type=Path,
        default=Path(
            "/data/workspace/lli21/data/26-4-21/"
            "2026_04_16_15h35m_56s/xrpld_2.6.0-bug0-local/"
            "delay-sparse_rules__partition-bi_part_groups__byzz-sparse_rules/"
            "validation_distribution_entropy/G258T3"
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional JSON output path. Prints to stdout when omitted.",
    )
    parser.add_argument(
        "--tex-out",
        type=Path,
        default=None,
        help="Optional LaTeX output path for a seq x node trie table.",
    )
    parser.add_argument(
        "--seq-from",
        type=int,
        default=None,
        help="Optional inclusive lower bound for displayed sequences.",
    )
    parser.add_argument(
        "--seq-to",
        type=int,
        default=None,
        help="Optional inclusive upper bound for displayed sequences.",
    )
    args = parser.parse_args()

    parsed = parse_trie(args.log_dir)

    if args.tex_out is not None:
        tex_path = write_trie_table_tex(
            parsed,
            args.tex_out,
            seq_from=args.seq_from,
            seq_to=args.seq_to,
        )
        print(f"Wrote trie table TeX to {tex_path}")

    if args.out is not None:
        text = json.dumps(parsed, indent=2, sort_keys=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"Wrote parsed trie snapshots to {args.out}")
    elif args.tex_out is None:
        print(json.dumps(parsed, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
