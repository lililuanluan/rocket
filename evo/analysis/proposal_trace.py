from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import yaml

from protos.packet_pb2 import Packet as ProtoPacket
from rocket_controller.encoder_decoder import (
    DecodingNotSupportedError,
    PacketEncoderDecoder,
)

from evo.preferred import parse_trie
from evo.proposal import parse_proposals

from .cases import resolve_iteration_dir, resolve_live_logs_dir
from .utils import analysis_dir


TIMESTAMP_RE = re.compile(
    r"^(\d{4}-[A-Za-z]{3}-\d{2} \d{2}:\d{2}:\d{2}\.\d+ UTC)\s"
)
VALIDATOR_DEBUG_RE = re.compile(r"validator_(\d+)_debug\.txt$")
VALIDATOR_LOG_RE = re.compile(r"validator_(\d+)_log\.txt$")
ROUND_START_RE = re.compile(
    r"ConsensusLogger onAccept: duration ([0-9.]+)s\. "
    r"startRoundInternal transitioned to ConsensusPhase::open, "
    r"previous ledgerID: ([A-F0-9]+), seq: (\d+)\. "
    r"number of peer proposals,previous proposers: (\d+),(\d+)\."
)
TIMER_LINE_RE = re.compile(r"ConsensusLogger Heartbeat Timer:")
TIMER_PHASE_RE = re.compile(r"Phase ([A-Za-z]+)\.")
TIMER_PREV_LEDGER_RE = re.compile(r"previous ledger ([A-F0-9]+)\.")
WORKING_SEQ_RE = re.compile(r"working seq: (\d+)")
PROPOSERS_RE = re.compile(r"Proposers:(\d+) nw:(\d+) thrV:(\d+) thrC:(\d+)")
CHECK_CONSENSUS_RE = re.compile(
    r"checkConsensus: prop=(\d+)/(\d+) agree=(\d+) validated=(\d+) time=(\d+)/(\d+)"
)
POSITION_CHANGE_RE = re.compile(r"Position change: CTime (\d+), tx ([A-F0-9]+)")
CCTIME_RE = re.compile(r"CCTime: seq (\d+): (\d+) has (\d+), (\d+) required")
PROPOSAL_DISAGREE_RE = re.compile(
    r"Proposal disagreement: Peer ([A-F0-9]+) has ([A-F0-9]+)"
)
CREATE_DISPUTES_RE = re.compile(r"createDisputes ([A-F0-9]+) to ([A-F0-9]+)")
REPORT_PREV_RE = re.compile(r"Report: Prev = ([A-F0-9]+):(\d+)")
REPORT_TXSET_RE = re.compile(r"Report: Transaction Set = ([A-F0-9]+), close (\d+)")
BUILT_LEDGER_RE = re.compile(r"Built ledger #(\d+): ([A-F0-9]+)")
CNF_VAL_RE = re.compile(r"CNF Val ([A-F0-9]+)")
SUBMIT_HASH_RE = re.compile(r'"hash":"([A-F0-9]+)"')
TRIE_RE = re.compile(r"ValidationTrie (\{.*\})$")
ZERO_HASH = "0" * 64
RIPPLE_ALPHABET = b"rpshnaf39wBUDNEGHJKLM4PQRST7VWXYZ2bcdeCg65jkm8oFqi1tuvAxyz"


@dataclass
class RoundWindow:
    node: int
    start_timestamp: str
    start_dt: datetime
    prev_ledger: str
    prev_seq: int
    working_seq: int
    previous_peer_proposals: int
    current_peer_proposals: int
    source_file: str
    source_line: int


def _extract_timestamp(line: str) -> str | None:
    match = TIMESTAMP_RE.match(line)
    return match.group(1) if match else None


def _parse_timestamp(timestamp: str) -> datetime:
    match = re.match(
        r"(\d{4}-[A-Za-z]{3}-\d{2} \d{2}:\d{2}:\d{2})\.(\d+) UTC$", timestamp
    )
    if not match:
        return datetime.strptime(timestamp, "%Y-%b-%d %H:%M:%S UTC").replace(
            tzinfo=timezone.utc
        )

    whole = match.group(1)
    fraction = (match.group(2) + "000000")[:6]
    dt = datetime.strptime(whole, "%Y-%b-%d %H:%M:%S")
    return dt.replace(microsecond=int(fraction), tzinfo=timezone.utc)


def _json_dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _format_timestamp(dt: datetime) -> str:
    return dt.strftime("%Y-%b-%d %H:%M:%S.%f UTC")


def _hash_short(value: str | None) -> str:
    if not value:
        return ""
    return value[:8]


def _match_validator_node(log_path: Path) -> int | None:
    match = VALIDATOR_DEBUG_RE.fullmatch(log_path.name)
    if match:
        return int(match.group(1))
    match = VALIDATOR_LOG_RE.fullmatch(log_path.name)
    if match:
        return int(match.group(1))
    return None


def _select_log_files(live_logs_dir: Path) -> dict[int, Path]:
    node_to_debug: dict[int, Path] = {}
    node_to_log: dict[int, Path] = {}

    for path in sorted(live_logs_dir.glob("validator_*_debug.txt")):
        node = _match_validator_node(path)
        if node is not None:
            node_to_debug[node] = path

    for path in sorted(live_logs_dir.glob("validator_*_log.txt")):
        node = _match_validator_node(path)
        if node is not None:
            node_to_log[node] = path

    selected: dict[int, Path] = {}
    for node in sorted(set(node_to_debug) | set(node_to_log)):
        selected[node] = node_to_debug.get(node, node_to_log[node])
    return selected


def _balanced_json_substring(text: str, start_idx: int) -> str | None:
    depth = 0
    in_string = False
    escape = False
    for idx in range(start_idx, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start_idx : idx + 1]
    return None


def _extract_json_after_marker(line: str, marker: str) -> dict[str, Any] | None:
    marker_idx = line.find(marker)
    if marker_idx < 0:
        return None
    brace_idx = line.find("{", marker_idx)
    if brace_idx < 0:
        return None
    json_text = _balanced_json_substring(line, brace_idx)
    if not json_text:
        return None
    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        return None


def _tip_hash_from_trie_node(node: dict[str, Any]) -> str:
    span = str(node.get("span", ""))
    if "[" in span:
        return span.split("[", 1)[0]
    return node.get("startID", "")


def _walk_trie_nodes(node: dict[str, Any]) -> Iterable[dict[str, Any]]:
    yield node
    for child in node.get("children", []) or []:
        yield from _walk_trie_nodes(child)


def _summarize_trie_json(trie_json: dict[str, Any] | None) -> tuple[str, str]:
    if not trie_json:
        return "", ""
    seq_support = trie_json.get("seq_support", {}) or {}
    leaves: list[str] = []
    root = trie_json.get("trie")
    if isinstance(root, dict):
        for node in _walk_trie_nodes(root):
            children = node.get("children", []) or []
            if children:
                continue
            tip_hash = _tip_hash_from_trie_node(node)
            tip_support = node.get("tipSupport", "")
            seq = node.get("seq", "")
            leaves.append(f"{_hash_short(tip_hash)}@{seq}:{tip_support}")
    return _json_dumps(seq_support or {}), ";".join(sorted(leaves))


def _summarize_trie_snapshot(snapshot: dict[str, Any] | None) -> tuple[str, str]:
    if not snapshot:
        return "", ""
    return _summarize_trie_json(snapshot.get("trie"))


def _base58_encode_ripple(data: bytes) -> str:
    num = int.from_bytes(data, byteorder="big")
    encoded: list[int] = []
    while num > 0:
        num, remainder = divmod(num, 58)
        encoded.append(RIPPLE_ALPHABET[remainder])
    for byte in data:
        if byte == 0:
            encoded.append(RIPPLE_ALPHABET[0])
        else:
            break
    return bytes(reversed(encoded)).decode("ascii")


def _public_key_bytes_to_node_public_key(pubkey_bytes: bytes) -> str:
    import hashlib

    payload = b"\x1c" + pubkey_bytes
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return _base58_encode_ripple(payload + checksum)


def _load_node_info(iteration_dir: Path) -> tuple[dict[int, str], dict[str, int]]:
    candidates = sorted(iteration_dir.glob("node_info-*.csv"))
    if not candidates:
        raise FileNotFoundError(f"No node_info-*.csv under {iteration_dir}")

    id_to_pubkey: dict[int, str] = {}
    pubkey_to_id: dict[str, int] = {}
    with candidates[0].open(newline="", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            node = int(row["node_id"])
            pubkey = row["public_key"]
            id_to_pubkey[node] = pubkey
            pubkey_to_id[pubkey] = node
    return id_to_pubkey, pubkey_to_id


def _load_planned_transactions(case_dir: Path) -> dict[str, dict[str, Any]]:
    transaction_log = resolve_iteration_dir(case_dir) / "transaction-1.csv"
    network_input = case_dir / "network_input.yaml"

    unique_txs: dict[str, dict[str, Any]] = {}
    with transaction_log.open(newline="", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tx_hash = row["tx_hash"]
            if tx_hash in unique_txs:
                continue
            unique_txs[tx_hash] = {
                "tx_hash": tx_hash,
                "sender_account_alias": row["sender_account_alias"],
                "receiver_account_alias": row["receiver_account_alias"],
                "amount": row["amount"],
                "account_sequence": int(row["sequence"]),
                "validated": row["validated"],
                "intended_seq": None,
                "submitter_node": None,
                "submit_timestamps": [],
            }

    config = yaml.safe_load(network_input.read_text(encoding="utf-8")) or {}
    regular_templates = (config.get("transactions") or {}).get("regular") or []
    template_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for template_idx, template in enumerate(regular_templates):
        key = (
            str(template.get("sender_account")),
            str(template.get("destination_account")),
            str(template.get("amount")),
        )
        seqs = [int(seq) for seq in template.get("in_seq") or []]
        template_groups[key].append(
            {
                "template_idx": template_idx,
                "sender_account_alias": str(template.get("sender_account")),
                "receiver_account_alias": str(template.get("destination_account")),
                "amount": str(template.get("amount")),
                "peer_id": int(template.get("peer_id")),
                "intended_seqs": sorted(seqs),
            }
        )

    actual_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for tx in unique_txs.values():
        key = (
            str(tx["sender_account_alias"]),
            str(tx["receiver_account_alias"]),
            str(tx["amount"]),
        )
        actual_groups[key].append(tx)

    for key, templates in template_groups.items():
        actuals = sorted(actual_groups.get(key, []), key=lambda row: row["account_sequence"])
        if not actuals:
            continue
        cursor = 0
        for template in templates:
            seqs = template["intended_seqs"]
            count = min(len(seqs), max(0, len(actuals) - cursor))
            for offset in range(count):
                actuals[cursor + offset]["intended_seq"] = seqs[offset]
                actuals[cursor + offset]["planned_peer_id"] = template["peer_id"]
                actuals[cursor + offset]["template_idx"] = template["template_idx"]
            cursor += count

    return unique_txs


def _scan_submit_events(
    log_files: dict[int, Path],
    tx_catalog: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node, log_path in log_files.items():
        for line_no, line in enumerate(
            log_path.read_text(encoding="utf-8", errors="ignore").splitlines(), start=1
        ):
            timestamp = _extract_timestamp(line)
            if not timestamp or '"tx_json"' not in line or '"hash":"' not in line:
                continue
            match = SUBMIT_HASH_RE.search(line)
            if not match:
                continue
            tx_hash = match.group(1)
            tx_info = tx_catalog.get(tx_hash)
            if tx_info is None:
                continue
            tx_info["submit_timestamps"].append(timestamp)
            if tx_info.get("submitter_node") is None:
                tx_info["submitter_node"] = node
            rows.append(
                {
                    "timestamp": timestamp,
                    "sort_key": _parse_timestamp(timestamp).isoformat(),
                    "node": node,
                    "working_seq": tx_info.get("intended_seq") or "",
                    "prev_seq": "",
                    "prev_ledger": "",
                    "event_type": "tx_submit",
                    "sender_node": node,
                    "receiver_node": node,
                    "transport_sender_node": "",
                    "transport_receiver_node": "",
                    "recipient_nodes": "",
                    "proposal_seq": "",
                    "position_hash": "",
                    "position_kind": "",
                    "close_time": "",
                    "planned_tx_hashes_for_seq": tx_hash,
                    "planned_tx_briefs_for_seq": _tx_brief(tx_info),
                    "observed_dispute_tx_hashes": "",
                    "proposers": "",
                    "needed_weight": "",
                    "thr_v": "",
                    "thr_c": "",
                    "agreeing": "",
                    "total": "",
                    "agree": "",
                    "validated": "",
                    "position_change_close_time": "",
                    "position_change_hash": "",
                    "close_time_votes": "",
                    "proposal_disagreements": "",
                    "peer_positions": "",
                    "peer_position_counts": "",
                    "state_phase": "",
                    "state_have_time_consensus": "",
                    "report_built_seq": "",
                    "report_built_ledger": "",
                    "cnf_val": "",
                    "validation_trie_seq_support": "",
                    "validation_trie_leaves": "",
                    "source_file": log_path.name,
                    "source_line": line_no,
                    "action_row": "",
                    "notes": "submit reply observed in validator log",
                }
            )
    return rows


def _tx_brief(tx_info: dict[str, Any]) -> str:
    intended = tx_info.get("intended_seq")
    intended_text = "" if intended is None else f" seq={intended}"
    return (
        f"{tx_info['tx_hash'][:8]} "
        f"{tx_info['sender_account_alias']}->{tx_info['receiver_account_alias']} "
        f"amt={tx_info['amount']}{intended_text}"
    )


def _round_tx_lookup(tx_catalog: dict[str, dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
    lookup: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for tx in tx_catalog.values():
        intended = tx.get("intended_seq")
        if intended is None:
            continue
        lookup[int(intended)].append(tx)
    for seq in lookup:
        lookup[seq].sort(key=lambda tx: (tx["sender_account_alias"], tx["account_sequence"]))
    return lookup


def _decode_packet_hex(packet_hex: str) -> tuple[Any, int] | None:
    if not packet_hex:
        return None
    try:
        packet = ProtoPacket(data=bytes.fromhex(packet_hex))
        return PacketEncoderDecoder.decode_packet(packet)
    except (ValueError, DecodingNotSupportedError, Exception):
        return None


def _proposal_pubkey_to_node(message: Any, pubkey_to_id: dict[str, int]) -> int | None:
    try:
        pubkey_str = _public_key_bytes_to_node_public_key(bytes(message.nodePubKey))
    except Exception:
        return None
    return pubkey_to_id.get(pubkey_str)


def _load_action_proposal_rows(
    iteration_dir: Path,
    ledger_seq_map: dict[str, int],
    pubkey_to_id: dict[str, int],
    tx_by_seq: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    action_path = iteration_dir / "action-1.csv"
    rows: list[dict[str, Any]] = []
    with action_path.open(newline="", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):
            if row.get("message_type") != "TMProposeSet":
                continue
            packet_hex = row.get("possibly_mutated_packet_data") or row.get("packet_data") or ""
            decoded = _decode_packet_hex(packet_hex)
            if decoded is None:
                continue
            message, _ = decoded
            proposer_node = _proposal_pubkey_to_node(message, pubkey_to_id)
            previous_ledger = bytes(message.previousledger).hex().upper()
            prev_seq = ledger_seq_map.get(previous_ledger)
            working_seq = None if prev_seq is None else int(prev_seq) + 1
            position_hash = bytes(message.currentTxHash).hex().upper()
            action_dt = datetime.fromtimestamp(
                int(row["timestamp"]) / 1000.0, tz=timezone.utc
            )
            transport_sender = int(row["from_node_id"])
            transport_receiver = int(row["to_node_id"])
            planned_txs = tx_by_seq.get(int(working_seq), []) if working_seq is not None else []
            rows.append(
                {
                    "timestamp": _format_timestamp(action_dt),
                    "sort_key": action_dt.isoformat(),
                    "node": proposer_node if proposer_node is not None else transport_sender,
                    "working_seq": "" if working_seq is None else working_seq,
                    "prev_seq": "" if prev_seq is None else prev_seq,
                    "prev_ledger": previous_ledger,
                    "event_type": (
                        "proposal_origin_send"
                        if proposer_node is not None and proposer_node == transport_sender
                        else "proposal_relay_send"
                    ),
                    "sender_node": proposer_node if proposer_node is not None else "",
                    "receiver_node": transport_receiver,
                    "transport_sender_node": transport_sender,
                    "transport_receiver_node": transport_receiver,
                    "recipient_nodes": str(transport_receiver),
                    "proposal_seq": int(message.proposeSeq),
                    "position_hash": position_hash,
                    "position_kind": "empty" if position_hash == ZERO_HASH else "nonempty",
                    "close_time": int(message.closeTime),
                    "planned_tx_hashes_for_seq": ";".join(tx["tx_hash"] for tx in planned_txs),
                    "planned_tx_briefs_for_seq": "; ".join(_tx_brief(tx) for tx in planned_txs),
                    "observed_dispute_tx_hashes": "",
                    "proposers": "",
                    "needed_weight": "",
                    "thr_v": "",
                    "thr_c": "",
                    "agreeing": "",
                    "total": "",
                    "agree": "",
                    "validated": "",
                    "position_change_close_time": "",
                    "position_change_hash": "",
                    "close_time_votes": "",
                    "proposal_disagreements": "",
                    "peer_positions": "",
                    "peer_position_counts": "",
                    "state_phase": "",
                    "state_have_time_consensus": "",
                    "report_built_seq": "",
                    "report_built_ledger": "",
                    "cnf_val": "",
                    "validation_trie_seq_support": "",
                    "validation_trie_leaves": "",
                    "source_file": action_path.name,
                    "source_line": "",
                    "action_row": row_num,
                    "notes": (
                        f"delay_ms={row.get('action','')} "
                        f"send_amount={row.get('send_amount','')}"
                    ).strip(),
                }
            )
    return rows


def _build_round_windows(
    log_files: dict[int, Path],
) -> dict[int, list[RoundWindow]]:
    result: dict[int, list[RoundWindow]] = defaultdict(list)
    for node, log_path in log_files.items():
        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line_no, line in enumerate(lines, start=1):
            timestamp = _extract_timestamp(line)
            if not timestamp:
                continue
            match = ROUND_START_RE.search(line)
            if not match:
                continue
            prev_ledger = match.group(2)
            prev_seq = int(match.group(3))
            result[node].append(
                RoundWindow(
                    node=node,
                    start_timestamp=timestamp,
                    start_dt=_parse_timestamp(timestamp),
                    prev_ledger=prev_ledger,
                    prev_seq=prev_seq,
                    working_seq=prev_seq + 1,
                    previous_peer_proposals=int(match.group(4)),
                    current_peer_proposals=int(match.group(5)),
                    source_file=log_path.name,
                    source_line=line_no,
                )
            )
    for node in result:
        result[node].sort(key=lambda item: item.start_dt)
    return result


def _find_active_round(
    round_windows: dict[int, list[RoundWindow]],
    node: int,
    timestamp: str,
) -> RoundWindow | None:
    windows = round_windows.get(node, [])
    if not windows:
        return None
    ts = _parse_timestamp(timestamp)
    current: RoundWindow | None = None
    for window in windows:
        if window.start_dt <= ts:
            current = window
        else:
            break
    return current


def _peer_positions_summary(
    peer_positions: dict[str, Any],
    overlay_map: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    summary: list[str] = []
    counter: Counter[str] = Counter()
    for overlay_id, info in sorted(peer_positions.items()):
        mapped = overlay_map.get(overlay_id, {})
        node = mapped.get("node")
        label = f"node{node}" if node is not None else overlay_id[:8]
        prev_ledger = str(info.get("previous_ledger", ""))
        tx_hash = str(info.get("transaction_hash", ""))
        propose_seq = info.get("propose_seq", "")
        close_time = info.get("close_time", "")
        summary.append(
            f"{label}:p{propose_seq}:{_hash_short(prev_ledger)}->{_hash_short(tx_hash)}@{close_time}"
        )
        counter[_hash_short(tx_hash)] += 1
    return "; ".join(summary), _json_dumps(dict(sorted(counter.items())))


def _planned_tx_strings(
    tx_by_seq: dict[int, list[dict[str, Any]]], working_seq: int | None
) -> tuple[str, str]:
    if working_seq is None:
        return "", ""
    planned = tx_by_seq.get(int(working_seq), [])
    return (
        ";".join(tx["tx_hash"] for tx in planned),
        "; ".join(_tx_brief(tx) for tx in planned),
    )


def _scan_local_log_events(
    log_files: dict[int, Path],
    round_windows: dict[int, list[RoundWindow]],
    overlay_map: dict[str, dict[str, Any]],
    ledger_seq_map: dict[str, int],
    tx_by_seq: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    for node, log_path in log_files.items():
        pending_cctime: list[dict[str, Any]] = []
        pending_disagreements: list[str] = []
        round_disputes: dict[int, set[str]] = defaultdict(set)

        lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line_no, line in enumerate(lines, start=1):
            timestamp = _extract_timestamp(line)
            if not timestamp:
                continue

            active_round = _find_active_round(round_windows, node, timestamp)
            active_working_seq = None if active_round is None else active_round.working_seq
            active_prev_seq = None if active_round is None else active_round.prev_seq
            active_prev_ledger = "" if active_round is None else active_round.prev_ledger
            planned_hashes, planned_briefs = _planned_tx_strings(tx_by_seq, active_working_seq)
            observed_disputes = (
                ";".join(sorted(round_disputes.get(active_working_seq, set())))
                if active_working_seq is not None
                else ""
            )

            cctime_match = CCTIME_RE.search(line)
            if cctime_match:
                pending_cctime.append(
                    {
                        "seq": int(cctime_match.group(1)),
                        "close_time": int(cctime_match.group(2)),
                        "count": int(cctime_match.group(3)),
                        "required": int(cctime_match.group(4)),
                    }
                )
                continue

            disagreement_match = PROPOSAL_DISAGREE_RE.search(line)
            if disagreement_match:
                overlay_id = disagreement_match.group(1)
                mapped = overlay_map.get(overlay_id, {})
                sender_node = mapped.get("node")
                sender_label = f"node{sender_node}" if sender_node is not None else overlay_id[:8]
                pending_disagreements.append(
                    f"{sender_label}:{disagreement_match.group(2)[:8]}"
                )
                continue

            dispute_match = CREATE_DISPUTES_RE.search(line)
            if dispute_match and active_working_seq is not None:
                round_disputes[active_working_seq].add(dispute_match.group(1))
                round_disputes[active_working_seq].add(dispute_match.group(2))
                rows.append(
                    {
                        "timestamp": timestamp,
                        "sort_key": _parse_timestamp(timestamp).isoformat(),
                        "node": node,
                        "working_seq": active_working_seq,
                        "prev_seq": "" if active_prev_seq is None else active_prev_seq,
                        "prev_ledger": active_prev_ledger,
                        "event_type": "create_disputes",
                        "sender_node": "",
                        "receiver_node": node,
                        "transport_sender_node": "",
                        "transport_receiver_node": "",
                        "recipient_nodes": "",
                        "proposal_seq": "",
                        "position_hash": "",
                        "position_kind": "",
                        "close_time": "",
                        "planned_tx_hashes_for_seq": planned_hashes,
                        "planned_tx_briefs_for_seq": planned_briefs,
                        "observed_dispute_tx_hashes": ";".join(
                            sorted(round_disputes[active_working_seq])
                        ),
                        "proposers": "",
                        "needed_weight": "",
                        "thr_v": "",
                        "thr_c": "",
                        "agreeing": "",
                        "total": "",
                        "agree": "",
                        "validated": "",
                        "position_change_close_time": "",
                        "position_change_hash": "",
                        "close_time_votes": "",
                        "proposal_disagreements": "",
                        "peer_positions": "",
                        "peer_position_counts": "",
                        "state_phase": "",
                        "state_have_time_consensus": "",
                        "report_built_seq": "",
                        "report_built_ledger": "",
                        "cnf_val": "",
                        "validation_trie_seq_support": "",
                        "validation_trie_leaves": "",
                        "source_file": log_path.name,
                        "source_line": line_no,
                        "action_row": "",
                        "notes": f"{dispute_match.group(1)} -> {dispute_match.group(2)}",
                    }
                )
                continue

            if TIMER_LINE_RE.search(line) and "updateOurPositions." in line:
                phase_match = TIMER_PHASE_RE.search(line)
                prev_match = TIMER_PREV_LEDGER_RE.search(line)
                proposers_match = PROPOSERS_RE.search(line)
                consensus_match = CHECK_CONSENSUS_RE.search(line)
                position_match = POSITION_CHANGE_RE.search(line)
                working_seq_match = WORKING_SEQ_RE.search(line)

                prev_ledger = active_prev_ledger
                prev_seq = active_prev_seq
                working_seq = active_working_seq

                if prev_match:
                    prev_ledger = prev_match.group(1)
                    prev_seq = ledger_seq_map.get(prev_ledger)
                    working_seq = None if prev_seq is None else int(prev_seq) + 1

                if working_seq is None and working_seq_match:
                    working_seq = int(working_seq_match.group(1))
                    prev_seq = working_seq - 1

                planned_hashes, planned_briefs = _planned_tx_strings(tx_by_seq, working_seq)
                observed_disputes = (
                    ";".join(sorted(round_disputes.get(working_seq, set())))
                    if working_seq is not None
                    else ""
                )

                rows.append(
                    {
                        "timestamp": timestamp,
                        "sort_key": _parse_timestamp(timestamp).isoformat(),
                        "node": node,
                        "working_seq": "" if working_seq is None else working_seq,
                        "prev_seq": "" if prev_seq is None else prev_seq,
                        "prev_ledger": prev_ledger,
                        "event_type": "timer_state",
                        "sender_node": "",
                        "receiver_node": node,
                        "transport_sender_node": "",
                        "transport_receiver_node": "",
                        "recipient_nodes": "",
                        "proposal_seq": "",
                        "position_hash": "",
                        "position_kind": "",
                        "close_time": "",
                        "planned_tx_hashes_for_seq": planned_hashes,
                        "planned_tx_briefs_for_seq": planned_briefs,
                        "observed_dispute_tx_hashes": observed_disputes,
                        "proposers": ""
                        if proposers_match is None
                        else int(proposers_match.group(1)),
                        "needed_weight": ""
                        if proposers_match is None
                        else int(proposers_match.group(2)),
                        "thr_v": ""
                        if proposers_match is None
                        else int(proposers_match.group(3)),
                        "thr_c": ""
                        if proposers_match is None
                        else int(proposers_match.group(4)),
                        "agreeing": ""
                        if consensus_match is None
                        else int(consensus_match.group(1)),
                        "total": ""
                        if consensus_match is None
                        else int(consensus_match.group(2)),
                        "agree": ""
                        if consensus_match is None
                        else int(consensus_match.group(3)),
                        "validated": ""
                        if consensus_match is None
                        else int(consensus_match.group(4)),
                        "position_change_close_time": ""
                        if position_match is None
                        else int(position_match.group(1)),
                        "position_change_hash": ""
                        if position_match is None
                        else position_match.group(2),
                        "close_time_votes": _json_dumps(pending_cctime),
                        "proposal_disagreements": "; ".join(pending_disagreements),
                        "peer_positions": "",
                        "peer_position_counts": "",
                        "state_phase": ""
                        if phase_match is None
                        else phase_match.group(1).lower(),
                        "state_have_time_consensus": (
                            "false" if "No close time consensus" in line else ""
                        ),
                        "report_built_seq": "",
                        "report_built_ledger": "",
                        "cnf_val": "",
                        "validation_trie_seq_support": "",
                        "validation_trie_leaves": "",
                        "source_file": log_path.name,
                        "source_line": line_no,
                        "action_row": "",
                        "notes": "",
                    }
                )
                pending_cctime = []
                pending_disagreements = []
                continue

            state_json = _extract_json_after_marker(line, "State on consensus change ")
            if state_json is None and "Unable to reach consensus " in line:
                state_json = _extract_json_after_marker(line, "Unable to reach consensus ")
            if state_json is None and "LedgerConsensus:ERR {" in line:
                state_json = _extract_json_after_marker(line, "LedgerConsensus:ERR ")
            if state_json is not None:
                working_seq = state_json.get("ledger_seq")
                prev_seq = None if working_seq in (None, "") else int(working_seq) - 1
                prev_ledger = str(
                    (state_json.get("our_position") or {}).get("previous_ledger", "")
                )
                planned_hashes, planned_briefs = _planned_tx_strings(tx_by_seq, working_seq)
                peer_summary, peer_counts = _peer_positions_summary(
                    state_json.get("peer_positions") or {}, overlay_map
                )
                rows.append(
                    {
                        "timestamp": timestamp,
                        "sort_key": _parse_timestamp(timestamp).isoformat(),
                        "node": node,
                        "working_seq": "" if working_seq in (None, "") else int(working_seq),
                        "prev_seq": "" if prev_seq is None else prev_seq,
                        "prev_ledger": prev_ledger,
                        "event_type": "state_snapshot",
                        "sender_node": "",
                        "receiver_node": node,
                        "transport_sender_node": "",
                        "transport_receiver_node": "",
                        "recipient_nodes": "",
                        "proposal_seq": (state_json.get("our_position") or {}).get(
                            "propose_seq", ""
                        ),
                        "position_hash": (state_json.get("our_position") or {}).get(
                            "transaction_hash", ""
                        ),
                        "position_kind": (
                            "empty"
                            if (state_json.get("our_position") or {}).get("transaction_hash")
                            == ZERO_HASH
                            else "nonempty"
                        ),
                        "close_time": (state_json.get("our_position") or {}).get(
                            "close_time", ""
                        ),
                        "planned_tx_hashes_for_seq": planned_hashes,
                        "planned_tx_briefs_for_seq": planned_briefs,
                        "observed_dispute_tx_hashes": ";".join(
                            sorted(
                                round_disputes.get(
                                    int(working_seq) if working_seq not in (None, "") else -1,
                                    set(),
                                )
                            )
                        ),
                        "proposers": state_json.get("proposers", ""),
                        "needed_weight": "",
                        "thr_v": "",
                        "thr_c": "",
                        "agreeing": "",
                        "total": "",
                        "agree": "",
                        "validated": "",
                        "position_change_close_time": "",
                        "position_change_hash": "",
                        "close_time_votes": _json_dumps(state_json.get("close_times") or {}),
                        "proposal_disagreements": "",
                        "peer_positions": peer_summary,
                        "peer_position_counts": peer_counts,
                        "state_phase": str(state_json.get("phase", "")),
                        "state_have_time_consensus": str(
                            state_json.get("have_time_consensus", "")
                        ).lower(),
                        "report_built_seq": "",
                        "report_built_ledger": "",
                        "cnf_val": "",
                        "validation_trie_seq_support": "",
                        "validation_trie_leaves": "",
                        "source_file": log_path.name,
                        "source_line": line_no,
                        "action_row": "",
                        "notes": "",
                    }
                )
                continue

            prev_report_match = REPORT_PREV_RE.search(line)
            if prev_report_match:
                prev_ledger = prev_report_match.group(1)
                prev_seq = int(prev_report_match.group(2))
                working_seq = prev_seq + 1
                planned_hashes, planned_briefs = _planned_tx_strings(tx_by_seq, working_seq)
                rows.append(
                    {
                        "timestamp": timestamp,
                        "sort_key": _parse_timestamp(timestamp).isoformat(),
                        "node": node,
                        "working_seq": working_seq,
                        "prev_seq": prev_seq,
                        "prev_ledger": prev_ledger,
                        "event_type": "round_report_prev",
                        "sender_node": "",
                        "receiver_node": node,
                        "transport_sender_node": "",
                        "transport_receiver_node": "",
                        "recipient_nodes": "",
                        "proposal_seq": "",
                        "position_hash": "",
                        "position_kind": "",
                        "close_time": "",
                        "planned_tx_hashes_for_seq": planned_hashes,
                        "planned_tx_briefs_for_seq": planned_briefs,
                        "observed_dispute_tx_hashes": ";".join(
                            sorted(round_disputes.get(working_seq, set()))
                        ),
                        "proposers": "",
                        "needed_weight": "",
                        "thr_v": "",
                        "thr_c": "",
                        "agreeing": "",
                        "total": "",
                        "agree": "",
                        "validated": "",
                        "position_change_close_time": "",
                        "position_change_hash": "",
                        "close_time_votes": "",
                        "proposal_disagreements": "",
                        "peer_positions": "",
                        "peer_position_counts": "",
                        "state_phase": "",
                        "state_have_time_consensus": "",
                        "report_built_seq": "",
                        "report_built_ledger": "",
                        "cnf_val": "",
                        "validation_trie_seq_support": "",
                        "validation_trie_leaves": "",
                        "source_file": log_path.name,
                        "source_line": line_no,
                        "action_row": "",
                        "notes": "",
                    }
                )
                continue

            report_txset_match = REPORT_TXSET_RE.search(line)
            if report_txset_match:
                working_seq = active_working_seq
                rows.append(
                    {
                        "timestamp": timestamp,
                        "sort_key": _parse_timestamp(timestamp).isoformat(),
                        "node": node,
                        "working_seq": "" if working_seq is None else working_seq,
                        "prev_seq": "" if active_prev_seq is None else active_prev_seq,
                        "prev_ledger": active_prev_ledger,
                        "event_type": "round_report_txset",
                        "sender_node": "",
                        "receiver_node": node,
                        "transport_sender_node": "",
                        "transport_receiver_node": "",
                        "recipient_nodes": "",
                        "proposal_seq": "",
                        "position_hash": report_txset_match.group(1),
                        "position_kind": (
                            "empty"
                            if report_txset_match.group(1) == ZERO_HASH
                            else "nonempty"
                        ),
                        "close_time": int(report_txset_match.group(2)),
                        "planned_tx_hashes_for_seq": planned_hashes,
                        "planned_tx_briefs_for_seq": planned_briefs,
                        "observed_dispute_tx_hashes": observed_disputes,
                        "proposers": "",
                        "needed_weight": "",
                        "thr_v": "",
                        "thr_c": "",
                        "agreeing": "",
                        "total": "",
                        "agree": "",
                        "validated": "",
                        "position_change_close_time": "",
                        "position_change_hash": "",
                        "close_time_votes": "",
                        "proposal_disagreements": "",
                        "peer_positions": "",
                        "peer_position_counts": "",
                        "state_phase": "",
                        "state_have_time_consensus": "",
                        "report_built_seq": "",
                        "report_built_ledger": "",
                        "cnf_val": "",
                        "validation_trie_seq_support": "",
                        "validation_trie_leaves": "",
                        "source_file": log_path.name,
                        "source_line": line_no,
                        "action_row": "",
                        "notes": "",
                    }
                )
                continue

            built_match = BUILT_LEDGER_RE.search(line)
            if built_match:
                working_seq = int(built_match.group(1))
                planned_hashes, planned_briefs = _planned_tx_strings(tx_by_seq, working_seq)
                rows.append(
                    {
                        "timestamp": timestamp,
                        "sort_key": _parse_timestamp(timestamp).isoformat(),
                        "node": node,
                        "working_seq": working_seq,
                        "prev_seq": working_seq - 1,
                        "prev_ledger": active_prev_ledger,
                        "event_type": "built_ledger",
                        "sender_node": "",
                        "receiver_node": node,
                        "transport_sender_node": "",
                        "transport_receiver_node": "",
                        "recipient_nodes": "",
                        "proposal_seq": "",
                        "position_hash": "",
                        "position_kind": "",
                        "close_time": "",
                        "planned_tx_hashes_for_seq": planned_hashes,
                        "planned_tx_briefs_for_seq": planned_briefs,
                        "observed_dispute_tx_hashes": ";".join(
                            sorted(round_disputes.get(working_seq, set()))
                        ),
                        "proposers": "",
                        "needed_weight": "",
                        "thr_v": "",
                        "thr_c": "",
                        "agreeing": "",
                        "total": "",
                        "agree": "",
                        "validated": "",
                        "position_change_close_time": "",
                        "position_change_hash": "",
                        "close_time_votes": "",
                        "proposal_disagreements": "",
                        "peer_positions": "",
                        "peer_position_counts": "",
                        "state_phase": "",
                        "state_have_time_consensus": "",
                        "report_built_seq": working_seq,
                        "report_built_ledger": built_match.group(2),
                        "cnf_val": "",
                        "validation_trie_seq_support": "",
                        "validation_trie_leaves": "",
                        "source_file": log_path.name,
                        "source_line": line_no,
                        "action_row": "",
                        "notes": "",
                    }
                )
                continue

            cnf_match = CNF_VAL_RE.search(line)
            if cnf_match:
                working_seq = active_working_seq
                rows.append(
                    {
                        "timestamp": timestamp,
                        "sort_key": _parse_timestamp(timestamp).isoformat(),
                        "node": node,
                        "working_seq": "" if working_seq is None else working_seq,
                        "prev_seq": "" if active_prev_seq is None else active_prev_seq,
                        "prev_ledger": active_prev_ledger,
                        "event_type": "cnf_validation",
                        "sender_node": "",
                        "receiver_node": node,
                        "transport_sender_node": "",
                        "transport_receiver_node": "",
                        "recipient_nodes": "",
                        "proposal_seq": "",
                        "position_hash": "",
                        "position_kind": "",
                        "close_time": "",
                        "planned_tx_hashes_for_seq": planned_hashes,
                        "planned_tx_briefs_for_seq": planned_briefs,
                        "observed_dispute_tx_hashes": observed_disputes,
                        "proposers": "",
                        "needed_weight": "",
                        "thr_v": "",
                        "thr_c": "",
                        "agreeing": "",
                        "total": "",
                        "agree": "",
                        "validated": "",
                        "position_change_close_time": "",
                        "position_change_hash": "",
                        "close_time_votes": "",
                        "proposal_disagreements": "",
                        "peer_positions": "",
                        "peer_position_counts": "",
                        "state_phase": "",
                        "state_have_time_consensus": "",
                        "report_built_seq": "",
                        "report_built_ledger": "",
                        "cnf_val": cnf_match.group(1),
                        "validation_trie_seq_support": "",
                        "validation_trie_leaves": "",
                        "source_file": log_path.name,
                        "source_line": line_no,
                        "action_row": "",
                        "notes": "",
                    }
                )
                continue

            trie_match = TRIE_RE.search(line)
            if trie_match:
                try:
                    trie = json.loads(trie_match.group(1))
                except json.JSONDecodeError:
                    trie = {}
                working_seq = active_working_seq
                trie_seq_support, trie_leaves = _summarize_trie_json(trie)
                rows.append(
                    {
                        "timestamp": timestamp,
                        "sort_key": _parse_timestamp(timestamp).isoformat(),
                        "node": node,
                        "working_seq": "" if working_seq is None else working_seq,
                        "prev_seq": "" if active_prev_seq is None else active_prev_seq,
                        "prev_ledger": active_prev_ledger,
                        "event_type": "validation_trie",
                        "sender_node": "",
                        "receiver_node": node,
                        "transport_sender_node": "",
                        "transport_receiver_node": "",
                        "recipient_nodes": "",
                        "proposal_seq": "",
                        "position_hash": "",
                        "position_kind": "",
                        "close_time": "",
                        "planned_tx_hashes_for_seq": planned_hashes,
                        "planned_tx_briefs_for_seq": planned_briefs,
                        "observed_dispute_tx_hashes": observed_disputes,
                        "proposers": "",
                        "needed_weight": "",
                        "thr_v": "",
                        "thr_c": "",
                        "agreeing": "",
                        "total": "",
                        "agree": "",
                        "validated": "",
                        "position_change_close_time": "",
                        "position_change_hash": "",
                        "close_time_votes": "",
                        "proposal_disagreements": "",
                        "peer_positions": "",
                        "peer_position_counts": "",
                        "state_phase": "",
                        "state_have_time_consensus": "",
                        "report_built_seq": "",
                        "report_built_ledger": "",
                        "cnf_val": "",
                        "validation_trie_seq_support": trie_seq_support,
                        "validation_trie_leaves": trie_leaves,
                        "source_file": log_path.name,
                        "source_line": line_no,
                        "action_row": "",
                        "notes": "",
                    }
                )
                continue

    return rows


def _build_receive_rows(
    parsed: dict[str, Any],
    round_windows: dict[int, list[RoundWindow]],
    tx_by_seq: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for receiver_node, node_data in sorted(parsed["nodes"].items()):
        for event in node_data["proposals"]:
            timestamp = event["timestamp"]
            active_round = _find_active_round(round_windows, int(receiver_node), timestamp)
            receiver_active_prev = "" if active_round is None else active_round.prev_ledger
            receiver_active_seq = "" if active_round is None else active_round.working_seq
            receiver_active_prev_seq = "" if active_round is None else active_round.prev_seq
            planned_hashes, planned_briefs = _planned_tx_strings(
                tx_by_seq, event.get("working_ledger_seq")
            )
            compatible = (
                "true"
                if receiver_active_prev and receiver_active_prev == event["previous_ledger"]
                else "false"
                if receiver_active_prev
                else ""
            )
            rows.append(
                {
                    "timestamp": timestamp,
                    "sort_key": _parse_timestamp(timestamp).isoformat(),
                    "node": int(receiver_node),
                    "working_seq": event.get("working_ledger_seq", ""),
                    "prev_seq": event.get("previous_ledger_seq", ""),
                    "prev_ledger": event["previous_ledger"],
                    "event_type": "proposal_receive",
                    "sender_node": ""
                    if event.get("sender_node") is None
                    else event["sender_node"],
                    "receiver_node": int(receiver_node),
                    "transport_sender_node": "",
                    "transport_receiver_node": int(receiver_node),
                    "recipient_nodes": str(receiver_node),
                    "proposal_seq": event["proposal_seq"],
                    "position_hash": event["position"],
                    "position_kind": (
                        "empty" if event["position"] == ZERO_HASH else "nonempty"
                    ),
                    "close_time": event["close_time"],
                    "planned_tx_hashes_for_seq": planned_hashes,
                    "planned_tx_briefs_for_seq": planned_briefs,
                    "observed_dispute_tx_hashes": "",
                    "proposers": "",
                    "needed_weight": "",
                    "thr_v": "",
                    "thr_c": "",
                    "agreeing": "",
                    "total": "",
                    "agree": "",
                    "validated": "",
                    "position_change_close_time": "",
                    "position_change_hash": "",
                    "close_time_votes": "",
                    "proposal_disagreements": "",
                    "peer_positions": "",
                    "peer_position_counts": "",
                    "state_phase": "",
                    "state_have_time_consensus": "",
                    "report_built_seq": "",
                    "report_built_ledger": "",
                    "cnf_val": "",
                    "validation_trie_seq_support": "",
                    "validation_trie_leaves": "",
                    "source_file": event["receiver_log"],
                    "source_line": event["line_no"],
                    "action_row": "",
                    "notes": (
                        f"sender_label={event.get('sender_label','')} "
                        f"is_bow_out={event.get('is_bow_out', False)} "
                        f"receiver_active_seq={receiver_active_seq} "
                        f"receiver_active_prev={_hash_short(receiver_active_prev)} "
                        f"compatible_with_receiver={compatible}"
                    ).strip(),
                }
            )
    return rows


def _is_local_position_row(row: dict[str, Any]) -> bool:
    if row["event_type"] == "timer_state":
        return row.get("position_change_hash") not in ("", None)
    if row["event_type"] in {"state_snapshot", "round_report_txset", "proposal_origin_send"}:
        return row.get("position_hash") not in ("", None)
    return False


def _local_position_hash(row: dict[str, Any]) -> str:
    if row["event_type"] == "timer_state":
        return str(row.get("position_change_hash", ""))
    return str(row.get("position_hash", ""))


def _annotate_receive_followups(rows: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        node = row.get("node")
        working_seq = row.get("working_seq")
        if node in ("", None) or working_seq in ("", None):
            continue
        grouped[(int(node), int(working_seq))].append(row)

    for group_rows in grouped.values():
        group_rows.sort(key=lambda row: (row["sort_key"], str(row["event_type"])))
        local_observations: list[tuple[int, dict[str, Any], str]] = []
        last_known_hash = ""
        for idx, row in enumerate(group_rows):
            if not _is_local_position_row(row):
                continue
            observed_hash = _local_position_hash(row)
            if observed_hash in ("", None):
                continue
            local_observations.append((idx, row, observed_hash))
            last_known_hash = observed_hash

        for idx, row in enumerate(group_rows):
            if row["event_type"] != "proposal_receive":
                continue

            previous_hash = ""
            for obs_idx, _obs_row, obs_hash in local_observations:
                if obs_idx >= idx:
                    break
                previous_hash = obs_hash

            next_observation: tuple[int, dict[str, Any], str] | None = None
            for observation in local_observations:
                if observation[0] > idx:
                    next_observation = observation
                    break

            row["known_local_position_before"] = previous_hash
            row["next_local_position_hash"] = ""
            row["next_local_position_event_type"] = ""
            row["next_local_position_timestamp"] = ""
            row["next_local_position_delay_ms"] = ""
            row["changed_after_receive"] = ""

            if next_observation is None:
                continue

            _obs_idx, next_row, next_hash = next_observation
            row["next_local_position_hash"] = next_hash
            row["next_local_position_event_type"] = str(next_row["event_type"])
            row["next_local_position_timestamp"] = str(next_row["timestamp"])
            delta_ms = (
                _parse_timestamp(str(next_row["timestamp"]))
                - _parse_timestamp(str(row["timestamp"]))
            ).total_seconds() * 1000.0
            row["next_local_position_delay_ms"] = int(round(delta_ms))
            if previous_hash:
                row["changed_after_receive"] = str(previous_hash != next_hash).lower()


def _build_round_rows(
    rows: list[dict[str, Any]],
    round_windows: dict[int, list[RoundWindow]],
    trie_snapshots: dict[int, dict[int, dict[str, Any]]],
    tx_by_seq: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("working_seq") in ("", None):
            continue
        grouped[(int(row["node"]), int(row["working_seq"]))].append(row)

    out_rows: list[dict[str, Any]] = []
    for (node, working_seq), group_rows in sorted(grouped.items()):
        group_rows.sort(key=lambda row: (row["sort_key"], row["event_type"]))
        round_window = None
        for window in round_windows.get(node, []):
            if window.working_seq == working_seq:
                round_window = window
                break
        planned = tx_by_seq.get(working_seq, [])
        receive_rows = [row for row in group_rows if row["event_type"] == "proposal_receive"]
        origin_send_rows = [
            row for row in group_rows if row["event_type"] == "proposal_origin_send"
        ]
        relay_rows = [row for row in group_rows if row["event_type"] == "proposal_relay_send"]
        timer_rows = [row for row in group_rows if row["event_type"] == "timer_state"]
        state_rows = [row for row in group_rows if row["event_type"] == "state_snapshot"]
        submit_rows = [row for row in group_rows if row["event_type"] == "tx_submit"]
        built_rows = [row for row in group_rows if row["event_type"] == "built_ledger"]
        cnf_rows = [row for row in group_rows if row["event_type"] == "cnf_validation"]
        local_position_observations = [
            _local_position_hash(row)
            for row in group_rows
            if _is_local_position_row(row) and _local_position_hash(row) not in ("", None)
        ]
        sender_counter = Counter(str(row.get("sender_node", "")) for row in receive_rows)
        position_counter = Counter(
            row["position_hash"] for row in receive_rows if row.get("position_hash")
        )
        trie_snapshot = trie_snapshots.get(node, {}).get(working_seq)
        trie_seq_support, trie_leaves = _summarize_trie_snapshot(trie_snapshot)
        last_state = state_rows[-1] if state_rows else None
        submitted_hashes = sorted(
            {
                row["planned_tx_hashes_for_seq"]
                for row in submit_rows
                if row["planned_tx_hashes_for_seq"]
            }
        )

        out_rows.append(
            {
                "node": node,
                "working_seq": working_seq,
                "prev_seq": "" if round_window is None else round_window.prev_seq,
                "prev_ledger": "" if round_window is None else round_window.prev_ledger,
                "start_timestamp": "" if round_window is None else round_window.start_timestamp,
                "end_timestamp": group_rows[-1]["timestamp"],
                "planned_tx_hashes_for_seq": ";".join(tx["tx_hash"] for tx in planned),
                "planned_tx_briefs_for_seq": "; ".join(_tx_brief(tx) for tx in planned),
                "local_submitted_tx_hashes": ";".join(submitted_hashes),
                "origin_send_count": len(origin_send_rows),
                "relay_send_count": len(relay_rows),
                "proposal_receive_count": len(receive_rows),
                "receive_sender_counts": _json_dumps(dict(sorted(sender_counter.items()))),
                "received_position_counts": _json_dumps(
                    {key[:8]: value for key, value in sorted(position_counter.items())}
                ),
                "timer_state_count": len(timer_rows),
                "state_snapshot_count": len(state_rows),
                "local_position_first": ""
                if not local_position_observations
                else local_position_observations[0],
                "local_position_last": ""
                if not local_position_observations
                else local_position_observations[-1],
                "report_tx_set_hash": next(
                    (row["position_hash"] for row in reversed(group_rows) if row["event_type"] == "round_report_txset"),
                    "",
                ),
                "built_ledger_hash": "" if not built_rows else built_rows[-1]["report_built_ledger"],
                "cnf_validation_hash": "" if not cnf_rows else cnf_rows[-1]["cnf_val"],
                "last_state_peer_positions": "" if last_state is None else last_state["peer_positions"],
                "last_state_peer_position_counts": ""
                if last_state is None
                else last_state["peer_position_counts"],
                "validation_trie_seq_support": trie_seq_support,
                "validation_trie_leaves": trie_leaves,
                "observed_dispute_tx_hashes": ";".join(
                    sorted(
                        {
                            tx
                            for row in group_rows
                            for tx in str(row.get("observed_dispute_tx_hashes", "")).split(";")
                            if tx
                        }
                    )
                ),
            }
        )
    return out_rows


def analyze_proposal_trace(
    case_dir: Path,
    *,
    nodes: list[int] | None = None,
    seqs: list[int] | None = None,
) -> dict[str, Any]:
    case_dir = case_dir.expanduser().resolve()
    iteration_dir = resolve_iteration_dir(case_dir)
    live_logs_dir = resolve_live_logs_dir(case_dir)

    _, pubkey_to_id = _load_node_info(iteration_dir)
    parsed = parse_proposals(case_dir)
    trie_snapshots = parse_trie(case_dir)
    tx_catalog = _load_planned_transactions(case_dir)
    tx_by_seq = _round_tx_lookup(tx_catalog)
    log_files = _select_log_files(live_logs_dir)
    round_windows = _build_round_windows(log_files)

    rows: list[dict[str, Any]] = []
    rows.extend(_load_action_proposal_rows(iteration_dir, parsed["ledger_seq_map"], pubkey_to_id, tx_by_seq))
    rows.extend(_build_receive_rows(parsed, round_windows, tx_by_seq))
    rows.extend(
        _scan_submit_events(log_files, tx_catalog)
    )
    rows.extend(
        _scan_local_log_events(
            log_files,
            round_windows,
            parsed["overlay_identity_map"],
            parsed["ledger_seq_map"],
            tx_by_seq,
        )
    )

    if nodes:
        node_set = {int(node) for node in nodes}
        rows = [
            row
            for row in rows
            if row.get("node") not in ("", None) and int(row["node"]) in node_set
        ]
    if seqs:
        seq_set = {int(seq) for seq in seqs}
        rows = [
            row
            for row in rows
            if row.get("working_seq") not in ("", None) and int(row["working_seq"]) in seq_set
        ]

    rows.sort(key=lambda row: (row["sort_key"], str(row["event_type"]), str(row["node"])))
    _annotate_receive_followups(rows)
    round_rows = _build_round_rows(rows, round_windows, trie_snapshots, tx_by_seq)

    tx_rows = []
    for tx_hash, tx_info in sorted(tx_catalog.items()):
        tx_rows.append(
            {
                "tx_hash": tx_hash,
                "sender_account_alias": tx_info["sender_account_alias"],
                "receiver_account_alias": tx_info["receiver_account_alias"],
                "amount": tx_info["amount"],
                "account_sequence": tx_info["account_sequence"],
                "intended_seq": "" if tx_info.get("intended_seq") is None else tx_info["intended_seq"],
                "submitter_node": "" if tx_info.get("submitter_node") is None else tx_info["submitter_node"],
                "submit_timestamps": ";".join(sorted(tx_info.get("submit_timestamps") or [])),
                "validated": tx_info["validated"],
                "brief": _tx_brief(tx_info),
            }
        )

    return {
        "case_dir": str(case_dir),
        "live_logs_dir": str(live_logs_dir),
        "event_rows": rows,
        "round_rows": round_rows,
        "tx_rows": tx_rows,
        "overlay_identity_map": parsed["overlay_identity_map"],
        "ledger_seq_map": parsed["ledger_seq_map"],
        "filters": {
            "nodes": [] if nodes is None else [int(node) for node in nodes],
            "seqs": [] if seqs is None else [int(seq) for seq in seqs],
        },
        "limitations": [
            "proposal messages carry the tx-set hash (currentTxHash), not the raw member transaction ids",
            "the events table therefore records the exact proposal position hash plus per-seq planned txs and directly observed dispute tx ids",
            "exact tx membership is only known for the empty set or when explicit dispute evidence exists in logs",
        ],
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = sorted({key for row in rows for key in row.keys()}) if rows else []
    with path.open("w", newline="", encoding="utf-8") as f:
        if fieldnames:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    return path


def run_proposal_trace(
    case_dir: Path,
    *,
    out_dir: Path | None = None,
    nodes: list[int] | None = None,
    seqs: list[int] | None = None,
) -> list[Path]:
    result = analyze_proposal_trace(case_dir, nodes=nodes, seqs=seqs)
    target_dir = analysis_dir(case_dir) if out_dir is None else out_dir.expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    json_path = target_dir / "proposal_round_trace.json"
    events_csv_path = target_dir / "proposal_round_trace_events.csv"
    rounds_csv_path = target_dir / "proposal_round_trace_rounds.csv"
    tx_csv_path = target_dir / "proposal_round_trace_transactions.csv"

    json_payload = dict(result)
    json_payload["event_rows"] = result["event_rows"]
    json_payload["round_rows"] = result["round_rows"]
    json_payload["tx_rows"] = result["tx_rows"]
    json_path.write_text(json.dumps(json_payload, indent=2, sort_keys=True), encoding="utf-8")
    _write_csv(events_csv_path, result["event_rows"])
    _write_csv(rounds_csv_path, result["round_rows"])
    _write_csv(tx_csv_path, result["tx_rows"])
    return [json_path, events_csv_path, rounds_csv_path, tx_csv_path]


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Trace proposal send/receive/local-state evolution for one case."
    )
    parser.add_argument("case_dir", type=Path, help="Case directory such as .../G12T14")
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="Output directory. Defaults to <case_dir>/analysis/.",
    )
    parser.add_argument(
        "--nodes",
        type=int,
        nargs="*",
        default=None,
        help="Optional node ids to keep.",
    )
    parser.add_argument(
        "--seqs",
        type=int,
        nargs="*",
        default=None,
        help="Optional working ledger sequences to keep.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    outputs = run_proposal_trace(
        args.case_dir,
        out_dir=args.out_dir,
        nodes=args.nodes,
        seqs=args.seqs,
    )
    for path in outputs:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
