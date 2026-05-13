from __future__ import annotations

import argparse
import csv
import html
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
except Exception:  # pragma: no cover - plotting is optional at runtime
    matplotlib = None
    mdates = None
    plt = None
    Line2D = None


VALIDATOR_DEBUG_RE = re.compile(r"validator_(\d+)_debug\.txt$")
TIMESTAMP_RE = re.compile(
    r"^(\d{4}-[A-Za-z]{3}-\d{2} \d{2}:\d{2}:\d{2}\.\d+ UTC)\s"
)
VALIDATION_ID_RE = re.compile(
    r"VALIDATION: .*?node_id: ([A-F0-9]+).*?base58: ([A-Za-z0-9]+)"
)
PROPOSAL_RE = re.compile(
    r"PROPOSAL proposal: previous_ledger: ([A-F0-9]+) "
    r"proposal_seq: (\d+) "
    r"position: ([A-F0-9]+) "
    r"close_time: ([0-9A-Za-z:.\- ]+ UTC) "
    r"now: ([0-9A-Za-z:.\- ]+ UTC) "
    r"is_bow_out:(\d+) "
    r"node_id: ([A-F0-9]+)"
)
ESTABLISH_START_RE = re.compile(r"closeLedger transitioned to ConsensusPhase::establish")
ESTABLISH_END_RE = re.compile(r"consensus phase establish changed to accepted\.")
CONVERGE_RE = re.compile(r"Converge cutoff \((\d+) participants\)")
REPORT_PREV_RE = re.compile(r"Report: Prev = ([A-F0-9]+):(\d+)")
REPORT_TXSET_RE = re.compile(r"Report: Transaction Set = ([A-F0-9]+), close (\d+)")
BUILT_LEDGER_RE = re.compile(r"Built ledger #(\d+): ([A-F0-9]+)")
CNF_VAL_RE = re.compile(r"CNF Val ([A-F0-9]+)")
ON_ACCEPT_RE = re.compile(r"ConsensusLogger onAccept: duration ([0-9.]+)s\.")
ROUND_START_RE = re.compile(
    r"ConsensusLogger onAccept: duration ([0-9.]+)s\. "
    r"startRoundInternal transitioned to ConsensusPhase::open, "
    r"previous ledgerID: ([A-F0-9]+), seq: (\d+)\. "
    r"number of peer proposals,previous proposers: (\d+),(\d+)\."
)
UPDATE_OUR_POSITIONS_RE = re.compile(
    r"updateOurPositions\. peerCutoff ([0-9A-Za-z:.\- ]+ UTC), "
    r"ourCutoff ([0-9A-Za-z:.\- ]+ UTC)\."
)
STALE_PROPOSAL_RE = re.compile(r"Removing stale proposal from ([A-F0-9]+)")


@dataclass
class ProposalEvent:
    receiver_node: int
    receiver_log: str
    line_no: int
    timestamp: str
    sender_overlay_id: str
    sender_node: int | None
    sender_label: str
    previous_ledger: str
    proposal_seq: int
    position: str
    close_time: str
    now: str
    is_bow_out: bool
    previous_ledger_seq: int | None = None
    working_ledger_seq: int | None = None


@dataclass
class EstablishPhaseEvent:
    receiver_node: int
    receiver_log: str
    start_line_no: int | None
    end_line_no: int
    start_timestamp: str | None
    end_timestamp: str
    duration_ms: float | None
    participants: int | None
    prev_ledger: str | None
    prev_seq: int | None
    tx_set: str | None
    consensus_close_time: int | None
    built_seq: int | None
    built_ledger: str | None
    on_accept_duration_s: float | None
    working_ledger_seq: int | None = None


@dataclass
class SequenceRoundContext:
    receiver_node: int
    receiver_log: str
    working_seq: int
    prev_seq: int
    prev_ledger: str
    start_line_no: int
    start_timestamp: str
    on_accept_duration_s: float | None
    replayed_peer_positions: int
    prev_proposers: int
    previous_accepted_line_no: int | None
    previous_accepted_timestamp: str | None
    first_update_line_no: int | None
    first_update_timestamp: str | None
    peer_cutoff: str | None
    our_cutoff: str | None
    stale_removed_overlay_ids: list[str]
    local_build_line_no: int | None
    local_build_timestamp: str | None
    local_build_ledger: str | None
    local_cnf_line_no: int | None
    local_cnf_timestamp: str | None


def _resolve_validator_log_dir(log_dir: str | Path) -> Path:
    path = Path(log_dir).expanduser().resolve()

    if path.is_file():
        if VALIDATOR_DEBUG_RE.fullmatch(path.name):
            return path.parent
        raise FileNotFoundError(f"Unsupported file input: {path}")

    if not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")

    if any(path.glob("validator_*_debug.txt")):
        return path

    iteration_live_logs = path / "iteration-1" / "validator_live_logs"
    if iteration_live_logs.is_dir():
        return iteration_live_logs

    live_logs = path / "validator_live_logs"
    if live_logs.is_dir():
        return live_logs

    raise FileNotFoundError(
        "Could not find validator debug logs under "
        f"{path}. Expected validator_*_debug.txt or iteration-1/validator_live_logs/"
    )


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


def _timestamp_tail(timestamp: str | None, with_fraction: bool = False) -> str | None:
    if not timestamp:
        return None

    if with_fraction:
        match = re.search(r" (\d{2}:\d{2}:\d{2}\.\d+)", timestamp)
        if match:
            return match.group(1)

    match = re.search(r" (\d{2}:\d{2}:\d{2})", timestamp)
    return match.group(1) if match else timestamp


def _hash_short(value: str | None) -> str:
    if not value:
        return "????????"
    return value[:8]


def _search_forward(
    lines: list[str], start_idx: int, pattern: re.Pattern[str], max_lines: int = 80
) -> re.Match[str] | None:
    upper = min(len(lines), start_idx + max_lines + 1)
    for idx in range(start_idx + 1, upper):
        match = pattern.search(lines[idx])
        if match:
            return match
    return None


def _find_iteration_dir(validator_log_dir: Path) -> Path | None:
    if validator_log_dir.name == "validator_live_logs":
        return validator_log_dir.parent

    for parent in validator_log_dir.parents:
        if re.fullmatch(r"iteration-\d+", parent.name):
            return parent

    return None


def _load_node_info_map(validator_log_dir: Path) -> dict[str, int]:
    iteration_dir = _find_iteration_dir(validator_log_dir)
    if iteration_dir is None:
        return {}

    for candidate in sorted(iteration_dir.glob("node_info-*.csv")):
        mapping: dict[str, int] = {}
        with candidate.open(newline="", encoding="utf-8", errors="ignore") as f:
            reader = csv.DictReader(f)
            for row in reader:
                node_value = row.get("node_id") or row.get("id")
                pubkey = row.get("public_key") or row.get("validation_public_key")
                if node_value is None or pubkey is None:
                    continue
                mapping[pubkey] = int(node_value)
        if mapping:
            return mapping

    return {}


def _build_overlay_identity_map(
    validator_log_dir: Path, node_info_map: dict[str, int]
) -> dict[str, dict[str, Any]]:
    overlay_map: dict[str, dict[str, Any]] = {}

    for log_path in sorted(validator_log_dir.glob("validator_*_debug.txt")):
        text = log_path.read_text(encoding="utf-8", errors="ignore")
        for overlay_id, base58 in VALIDATION_ID_RE.findall(text):
            info = overlay_map.setdefault(overlay_id, {"overlay_id": overlay_id})
            info["validation_public_key"] = base58
            if base58 in node_info_map:
                info["node"] = node_info_map[base58]

    for overlay_id, info in overlay_map.items():
        node = info.get("node")
        if node is not None:
            info["label"] = f"node{node}"
        else:
            info["label"] = overlay_id[:8]

    return overlay_map


def _parse_validator_file(
    log_path: Path, overlay_map: dict[str, dict[str, Any]]
) -> tuple[list[ProposalEvent], list[EstablishPhaseEvent]]:
    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    match = VALIDATOR_DEBUG_RE.fullmatch(log_path.name)
    if not match:
        raise ValueError(f"Unexpected validator log filename: {log_path.name}")

    receiver_node = int(match.group(1))
    proposals: list[ProposalEvent] = []
    phases: list[EstablishPhaseEvent] = []
    current_establish: dict[str, Any] | None = None

    for idx, line in enumerate(lines):
        timestamp = _extract_timestamp(line)

        proposal_match = PROPOSAL_RE.search(line)
        if proposal_match and timestamp:
            (
                previous_ledger,
                proposal_seq,
                position,
                close_time,
                now,
                is_bow_out,
                sender_overlay_id,
            ) = proposal_match.groups()
            sender_info = overlay_map.get(sender_overlay_id, {})
            proposals.append(
                ProposalEvent(
                    receiver_node=receiver_node,
                    receiver_log=log_path.name,
                    line_no=idx + 1,
                    timestamp=timestamp,
                    sender_overlay_id=sender_overlay_id,
                    sender_node=sender_info.get("node"),
                    sender_label=sender_info.get("label", sender_overlay_id[:8]),
                    previous_ledger=previous_ledger,
                    proposal_seq=int(proposal_seq),
                    position=position,
                    close_time=close_time,
                    now=now,
                    is_bow_out=bool(int(is_bow_out)),
                )
            )

        if ESTABLISH_START_RE.search(line) and timestamp:
            if current_establish is not None:
                phases.append(
                    EstablishPhaseEvent(
                        receiver_node=receiver_node,
                        receiver_log=log_path.name,
                        start_line_no=current_establish.get("start_line_no"),
                        end_line_no=current_establish.get("start_line_no")
                        or idx + 1,
                        start_timestamp=current_establish.get("start_timestamp"),
                        end_timestamp=current_establish.get("start_timestamp")
                        or timestamp,
                        duration_ms=None,
                        participants=None,
                        prev_ledger=None,
                        prev_seq=None,
                        tx_set=None,
                        consensus_close_time=None,
                        built_seq=None,
                        built_ledger=None,
                        on_accept_duration_s=None,
                    )
                )

            current_establish = {
                "start_line_no": idx + 1,
                "start_timestamp": timestamp,
            }

        if ESTABLISH_END_RE.search(line) and timestamp:
            participants_match = CONVERGE_RE.search(line)
            report_prev = _search_forward(lines, idx, REPORT_PREV_RE, max_lines=40)
            report_txset = _search_forward(lines, idx, REPORT_TXSET_RE, max_lines=40)
            built_match = _search_forward(lines, idx, BUILT_LEDGER_RE, max_lines=50)
            on_accept_match = _search_forward(lines, idx, ON_ACCEPT_RE, max_lines=120)

            start_timestamp = None if current_establish is None else current_establish.get(
                "start_timestamp"
            )
            start_dt = (
                None if start_timestamp is None else _parse_timestamp(start_timestamp)
            )
            end_dt = _parse_timestamp(timestamp)
            duration_ms = None
            if start_dt is not None:
                duration_ms = round((end_dt - start_dt).total_seconds() * 1000.0, 3)

            phases.append(
                EstablishPhaseEvent(
                    receiver_node=receiver_node,
                    receiver_log=log_path.name,
                    start_line_no=None
                    if current_establish is None
                    else current_establish.get("start_line_no"),
                    end_line_no=idx + 1,
                    start_timestamp=start_timestamp,
                    end_timestamp=timestamp,
                    duration_ms=duration_ms,
                    participants=None
                    if participants_match is None
                    else int(participants_match.group(1)),
                    prev_ledger=None
                    if report_prev is None
                    else report_prev.group(1),
                    prev_seq=None
                    if report_prev is None
                    else int(report_prev.group(2)),
                    tx_set=None
                    if report_txset is None
                    else report_txset.group(1),
                    consensus_close_time=None
                    if report_txset is None
                    else int(report_txset.group(2)),
                    built_seq=None
                    if built_match is None
                    else int(built_match.group(1)),
                    built_ledger=None
                    if built_match is None
                    else built_match.group(2),
                    on_accept_duration_s=None
                    if on_accept_match is None
                    else float(on_accept_match.group(1)),
                )
            )
            current_establish = None

    return proposals, phases


def parse_proposals(log_dir: str | Path) -> dict[str, Any]:
    """
    Parse received peer proposals and establish->accepted phase boundaries.

    The input may be:
    - a saved run directory such as .../G258T3
    - an iteration directory such as .../G258T3/iteration-1
    - a validator_live_logs directory
    - one validator_*_debug.txt file
    """

    validator_log_dir = _resolve_validator_log_dir(log_dir)
    node_info_map = _load_node_info_map(validator_log_dir)
    overlay_map = _build_overlay_identity_map(validator_log_dir, node_info_map)

    parsed_nodes: dict[int, dict[str, Any]] = {}
    for log_path in sorted(validator_log_dir.glob("validator_*_debug.txt")):
        match = VALIDATOR_DEBUG_RE.fullmatch(log_path.name)
        if not match:
            continue

        receiver_node = int(match.group(1))
        proposals, phases = _parse_validator_file(log_path, overlay_map)
        parsed_nodes[receiver_node] = {
            "receiver_node": receiver_node,
            "log_file": log_path.name,
            "proposal_count": len(proposals),
            "phase_count": len(phases),
            "proposals": [asdict(event) for event in proposals],
            "establish_phases": [asdict(event) for event in phases],
        }

    if not parsed_nodes:
        raise FileNotFoundError(
            f"No validator_*_debug.txt files found under {validator_log_dir}"
        )

    parsed = {
        "validator_log_dir": str(validator_log_dir),
        "overlay_identity_map": overlay_map,
        "node_info_map": node_info_map,
        "nodes": parsed_nodes,
    }
    _annotate_ledger_sequences(parsed)
    return parsed


def _annotate_ledger_sequences(parsed: dict[str, Any]) -> None:
    ledger_seq_map: dict[str, int] = {}

    for node_data in parsed["nodes"].values():
        for phase in node_data["establish_phases"]:
            prev_ledger = phase.get("prev_ledger")
            prev_seq = phase.get("prev_seq")
            built_ledger = phase.get("built_ledger")
            built_seq = phase.get("built_seq")

            if prev_ledger and prev_seq is not None:
                ledger_seq_map.setdefault(prev_ledger, int(prev_seq))
            if built_ledger and built_seq is not None:
                ledger_seq_map.setdefault(built_ledger, int(built_seq))

    for node_data in parsed["nodes"].values():
        for proposal in node_data["proposals"]:
            prev_seq = ledger_seq_map.get(proposal["previous_ledger"])
            proposal["previous_ledger_seq"] = prev_seq
            proposal["working_ledger_seq"] = (
                None if prev_seq is None else prev_seq + 1
            )

        for phase in node_data["establish_phases"]:
            prev_seq = phase.get("prev_seq")
            built_seq = phase.get("built_seq")
            phase["working_ledger_seq"] = (
                built_seq if built_seq is not None else None if prev_seq is None else prev_seq + 1
            )

    parsed["ledger_seq_map"] = ledger_seq_map


def _receiver_log_path(parsed: dict[str, Any], receiver_node: int) -> Path:
    validator_log_dir = Path(parsed["validator_log_dir"])
    node_data = parsed["nodes"].get(receiver_node)
    if node_data is None:
        raise ValueError(f"Receiver node{receiver_node} not present in parsed data")
    return validator_log_dir / str(node_data["log_file"])


def _find_sequence_round_context(
    parsed: dict[str, Any], receiver_node: int, working_seq: int
) -> SequenceRoundContext:
    if working_seq <= 0:
        raise ValueError("working_seq must be positive")

    log_path = _receiver_log_path(parsed, receiver_node)
    lines = log_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    target_prev_seq = working_seq - 1
    last_accepted_line_no: int | None = None
    last_accepted_timestamp: str | None = None

    start_line_no: int | None = None
    start_timestamp: str | None = None
    prev_ledger: str | None = None
    on_accept_duration_s: float | None = None
    replayed_peer_positions: int | None = None
    prev_proposers: int | None = None

    for idx, line in enumerate(lines, start=1):
        timestamp = _extract_timestamp(line)
        if ESTABLISH_END_RE.search(line) and timestamp:
            last_accepted_line_no = idx
            last_accepted_timestamp = timestamp

        round_start_match = ROUND_START_RE.search(line)
        if round_start_match and timestamp:
            prev_seq = int(round_start_match.group(3))
            if prev_seq != target_prev_seq:
                continue
            start_line_no = idx
            start_timestamp = timestamp
            on_accept_duration_s = float(round_start_match.group(1))
            prev_ledger = round_start_match.group(2)
            replayed_peer_positions = int(round_start_match.group(4))
            prev_proposers = int(round_start_match.group(5))
            break

    if start_line_no is None or start_timestamp is None or prev_ledger is None:
        raise ValueError(
            f"Could not find round start for node{receiver_node} working seq {working_seq}"
        )

    first_update_line_no: int | None = None
    first_update_timestamp: str | None = None
    peer_cutoff: str | None = None
    our_cutoff: str | None = None
    stale_removed_overlay_ids: list[str] = []
    local_build_line_no: int | None = None
    local_build_timestamp: str | None = None
    local_build_ledger: str | None = None
    local_cnf_line_no: int | None = None
    local_cnf_timestamp: str | None = None

    for idx in range(start_line_no, len(lines) + 1):
        line = lines[idx - 1]
        timestamp = _extract_timestamp(line)
        stale_match = STALE_PROPOSAL_RE.search(line)
        if stale_match and first_update_line_no is None:
            stale_removed_overlay_ids.append(stale_match.group(1))

        update_match = UPDATE_OUR_POSITIONS_RE.search(line)
        if update_match and timestamp and first_update_line_no is None:
            first_update_line_no = idx
            first_update_timestamp = timestamp
            peer_cutoff = update_match.group(1)
            our_cutoff = update_match.group(2)

        built_match = BUILT_LEDGER_RE.search(line)
        if (
            built_match
            and timestamp
            and local_build_line_no is None
            and int(built_match.group(1)) == working_seq
        ):
            local_build_line_no = idx
            local_build_timestamp = timestamp
            local_build_ledger = built_match.group(2)

        cnf_match = CNF_VAL_RE.search(line)
        if cnf_match and timestamp and local_cnf_line_no is None:
            cnf_ledger = cnf_match.group(1)
            if local_build_ledger is None:
                if local_build_line_no is not None:
                    local_cnf_line_no = idx
                    local_cnf_timestamp = timestamp
            elif cnf_ledger == local_build_ledger:
                local_cnf_line_no = idx
                local_cnf_timestamp = timestamp

        next_round_match = ROUND_START_RE.search(line)
        if idx > start_line_no and next_round_match:
            break

    return SequenceRoundContext(
        receiver_node=receiver_node,
        receiver_log=log_path.name,
        working_seq=working_seq,
        prev_seq=target_prev_seq,
        prev_ledger=prev_ledger,
        start_line_no=start_line_no,
        start_timestamp=start_timestamp,
        on_accept_duration_s=on_accept_duration_s,
        replayed_peer_positions=0 if replayed_peer_positions is None else replayed_peer_positions,
        prev_proposers=0 if prev_proposers is None else prev_proposers,
        previous_accepted_line_no=last_accepted_line_no,
        previous_accepted_timestamp=last_accepted_timestamp,
        first_update_line_no=first_update_line_no,
        first_update_timestamp=first_update_timestamp,
        peer_cutoff=peer_cutoff,
        our_cutoff=our_cutoff,
        stale_removed_overlay_ids=stale_removed_overlay_ids,
        local_build_line_no=local_build_line_no,
        local_build_timestamp=local_build_timestamp,
        local_build_ledger=local_build_ledger,
        local_cnf_line_no=local_cnf_line_no,
        local_cnf_timestamp=local_cnf_timestamp,
    )


def _proposal_status_before_round(
    proposal: ProposalEvent,
    prev_ledger: str,
    last10_lines: set[int],
    replay_current_line_no: int | None,
    compatible_last10_line_nos: set[int],
    peer_cutoff: str | None,
) -> dict[str, Any]:
    compatible = proposal.previous_ledger == prev_ledger
    in_last10 = proposal.line_no in last10_lines
    replayed = proposal.line_no in compatible_last10_line_nos
    is_replay_current = replay_current_line_no == proposal.line_no

    stale_at_first_update: bool | None = None
    if is_replay_current and peer_cutoff is not None:
        stale_at_first_update = _parse_timestamp(proposal.now) <= _parse_timestamp(peer_cutoff)

    if compatible and not in_last10:
        status = "compatible_evicted_before_open"
    elif is_replay_current:
        status = "replay_current"
    elif replayed:
        status = "replayed_then_superseded"
    elif compatible:
        status = "compatible_not_current"
    else:
        status = "other_prev"

    return {
        "compatible": compatible,
        "in_last10_at_open": in_last10,
        "replayed_at_open": replayed,
        "current_after_replay": is_replay_current,
        "stale_at_first_update": stale_at_first_update,
        "status": status,
    }


def build_sequence_report(
    parsed: dict[str, Any], receiver_node: int, working_seq: int
) -> dict[str, Any]:
    context = _find_sequence_round_context(parsed, receiver_node, working_seq)
    proposals = [
        ProposalEvent(**event) for event in parsed["nodes"][receiver_node]["proposals"]
    ]
    before_start = [proposal for proposal in proposals if proposal.line_no < context.start_line_no]

    window_start_line = (
        0 if context.previous_accepted_line_no is None else context.previous_accepted_line_no
    )
    window_end_line = (
        context.local_cnf_line_no
        if context.local_cnf_line_no is not None
        else context.local_build_line_no
        if context.local_build_line_no is not None
        else context.first_update_line_no
        if context.first_update_line_no is not None
        else context.start_line_no
    )
    window_proposals = [
        proposal
        for proposal in proposals
        if window_start_line < proposal.line_no <= window_end_line
    ]

    by_sender: dict[str, list[ProposalEvent]] = {}
    for proposal in before_start:
        by_sender.setdefault(proposal.sender_overlay_id, []).append(proposal)

    stale_removed_set = set(context.stale_removed_overlay_ids)
    summary_rows: list[dict[str, Any]] = []
    detailed_rows: list[dict[str, Any]] = []

    sender_state: dict[str, dict[str, Any]] = {}
    for sender_overlay_id, sender_history in by_sender.items():
        last10 = sender_history[-10:]
        last10_lines = {proposal.line_no for proposal in last10}
        compatible_ever = [
            proposal
            for proposal in sender_history
            if proposal.previous_ledger == context.prev_ledger
        ]
        compatible_last10 = [
            proposal for proposal in last10 if proposal.previous_ledger == context.prev_ledger
        ]

        replay_current: ProposalEvent | None = None
        replay_dead = False
        replayed_line_nos: set[int] = set()
        for proposal in compatible_last10:
            if replay_dead:
                break
            if proposal.is_bow_out:
                replay_dead = True
                replay_current = None
                replayed_line_nos.add(proposal.line_no)
                continue
            if replay_current is None or proposal.proposal_seq > replay_current.proposal_seq:
                replay_current = proposal
            replayed_line_nos.add(proposal.line_no)

        stale_at_first_update: bool | None = None
        if replay_current is not None and context.peer_cutoff is not None:
            stale_at_first_update = _parse_timestamp(replay_current.now) <= _parse_timestamp(
                context.peer_cutoff
            )

        sender_label = sender_history[-1].sender_label
        if compatible_last10 and replay_current is not None:
            status = "replayed at open"
            if stale_at_first_update:
                status += "; stale by first update"
            elif sender_overlay_id in stale_removed_set:
                status += "; removed before first update"
        elif compatible_ever and not compatible_last10:
            status = "compatible seen earlier, evicted from last-10"
        elif compatible_last10 and replay_current is None:
            status = "compatible history present, but no current replay position"
        else:
            status = "no compatible proposal seen"

        summary_rows.append(
            {
                "proposer": sender_label,
                "sender_overlay_id": sender_overlay_id,
                "total_before_open": len(sender_history),
                "last10_size": len(last10),
                "compatible_ever": len(compatible_ever),
                "compatible_in_last10": len(compatible_last10),
                "compatible_last10_lines": ",".join(
                    str(proposal.line_no) for proposal in compatible_last10
                )
                or "-",
                "replay_current_line": None if replay_current is None else replay_current.line_no,
                "replay_current_proposal_seq": None
                if replay_current is None
                else replay_current.proposal_seq,
                "replay_current_position": None
                if replay_current is None
                else replay_current.position,
                "replay_current_close_time": None
                if replay_current is None
                else replay_current.close_time,
                "replay_current_now": None if replay_current is None else replay_current.now,
                "stale_at_first_update": stale_at_first_update,
                "stale_removed_before_update": sender_overlay_id in stale_removed_set,
                "status": status,
            }
        )

        sender_state[sender_overlay_id] = {
            "last10_lines": last10_lines,
            "compatible_last10_line_nos": replayed_line_nos,
            "replay_current_line_no": None if replay_current is None else replay_current.line_no,
        }

    for proposal in window_proposals:
        state = sender_state.get(
            proposal.sender_overlay_id,
            {
                "last10_lines": set(),
                "compatible_last10_line_nos": set(),
                "replay_current_line_no": None,
            },
        )
        row_state = _proposal_status_before_round(
            proposal,
            context.prev_ledger,
            state["last10_lines"],
            state["replay_current_line_no"],
            state["compatible_last10_line_nos"],
            context.peer_cutoff,
        )
        stage = "before_open"
        if proposal.line_no >= context.start_line_no:
            if (
                context.first_update_line_no is not None
                and proposal.line_no >= context.first_update_line_no
            ):
                stage = "after_first_update_before_validation"
            else:
                stage = "after_open_before_first_update"
            if not row_state["compatible"]:
                row_state["status"] = "rejected_after_open_incompatible_prev"

        detailed_rows.append(
            {
                "line_no": proposal.line_no,
                "timestamp": proposal.timestamp,
                "stage": stage,
                "proposer": proposal.sender_label,
                "sender_overlay_id": proposal.sender_overlay_id,
                "previous_ledger": proposal.previous_ledger,
                "previous_ledger_seq": proposal.previous_ledger_seq,
                "proposal_seq": proposal.proposal_seq,
                "position": proposal.position,
                "close_time": proposal.close_time,
                "proposal_now": proposal.now,
                "is_bow_out": proposal.is_bow_out,
                **row_state,
            }
        )

    summary_rows.sort(key=lambda row: (row["proposer"], row["sender_overlay_id"]))
    detailed_rows.sort(key=lambda row: row["line_no"])

    return {
        "context": asdict(context),
        "summary_rows": summary_rows,
        "detail_rows": detailed_rows,
    }


def _iter_flattened_events(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for node_data in parsed["nodes"].values():
        for proposal in node_data["proposals"]:
            row = dict(proposal)
            row["event_type"] = "proposal"
            rows.append(row)
        for phase in node_data["establish_phases"]:
            row = dict(phase)
            row["event_type"] = "establish_end"
            rows.append(row)
    rows.sort(
        key=lambda row: (
            row.get("timestamp")
            or row.get("end_timestamp")
            or row.get("start_timestamp")
            or ""
        )
    )
    return rows


def write_events_csv(parsed: dict[str, Any], out_path: str | Path) -> Path:
    out = Path(out_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    rows = _iter_flattened_events(parsed)
    fieldnames = sorted({key for row in rows for key in row.keys()})
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return out


def write_sequence_report_json(report: dict[str, Any], out_path: str | Path) -> Path:
    out = Path(out_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return out


def write_sequence_report_csvs(
    report: dict[str, Any],
    summary_out_path: str | Path,
    detail_out_path: str | Path,
) -> tuple[Path, Path]:
    summary_out = Path(summary_out_path).expanduser().resolve()
    detail_out = Path(detail_out_path).expanduser().resolve()
    summary_out.parent.mkdir(parents=True, exist_ok=True)
    detail_out.parent.mkdir(parents=True, exist_ok=True)

    summary_rows = report["summary_rows"]
    detail_rows = report["detail_rows"]

    with summary_out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "proposer",
                "sender_overlay_id",
                "total_before_open",
                "last10_size",
                "compatible_ever",
                "compatible_in_last10",
                "compatible_last10_lines",
                "replay_current_line",
                "replay_current_proposal_seq",
                "replay_current_position",
                "replay_current_close_time",
                "replay_current_now",
                "stale_at_first_update",
                "stale_removed_before_update",
                "status",
            ],
        )
        writer.writeheader()
        writer.writerows(summary_rows)

    with detail_out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "line_no",
                "timestamp",
                "stage",
                "proposer",
                "sender_overlay_id",
                "previous_ledger",
                "previous_ledger_seq",
                "proposal_seq",
                "position",
                "close_time",
                "proposal_now",
                "is_bow_out",
                "compatible",
                "in_last10_at_open",
                "replayed_at_open",
                "current_after_replay",
                "stale_at_first_update",
                "status",
            ],
        )
        writer.writeheader()
        writer.writerows(detail_rows)

    return summary_out, detail_out


def _parse_node_selection(values: list[int] | None, parsed: dict[str, Any]) -> list[int]:
    all_nodes = sorted(int(node) for node in parsed["nodes"].keys())
    if not values:
        return all_nodes
    selected = [node for node in all_nodes if node in set(values)]
    if not selected:
        raise ValueError(f"Requested nodes {values} are not present in parsed data")
    return selected


def _collect_plot_events(
    parsed: dict[str, Any], selected_nodes: list[int]
) -> tuple[list[ProposalEvent], list[EstablishPhaseEvent]]:
    proposals: list[ProposalEvent] = []
    phases: list[EstablishPhaseEvent] = []

    for receiver_node in selected_nodes:
        node_data = parsed["nodes"][receiver_node]
        proposals.extend(ProposalEvent(**event) for event in node_data["proposals"])
        phases.extend(
            EstablishPhaseEvent(**event) for event in node_data["establish_phases"]
        )

    return proposals, phases


def _sender_color(
    sender_node: int | None, known_sender_colors: dict[int, str], fallback: str
) -> str:
    if sender_node is None:
        return fallback
    return known_sender_colors.get(sender_node, fallback)


def _sender_key(event: ProposalEvent) -> str:
    if event.sender_node is not None:
        return f"node:{event.sender_node}"
    return f"overlay:{event.sender_overlay_id}"


def _build_sender_positions(events: list[ProposalEvent]) -> tuple[list[str], dict[str, int]]:
    sender_keys: list[str] = []
    for event in events:
        key = _sender_key(event)
        if key not in sender_keys:
            sender_keys.append(key)
    if not sender_keys:
        sender_keys.append("phase")
    return sender_keys, {key: idx for idx, key in enumerate(sender_keys)}


def _write_timeline_svg(
    parsed: dict[str, Any],
    out_path: Path,
    selected_nodes: list[int],
    annotate: bool,
    title: str | None,
) -> Path:
    proposals, phases = _collect_plot_events(parsed, selected_nodes)
    if not proposals and not phases:
        raise ValueError("No proposal or establish events available to plot")

    proposal_times = [_parse_timestamp(event.timestamp) for event in proposals]
    phase_start_times = [
        _parse_timestamp(event.start_timestamp)
        for event in phases
        if event.start_timestamp is not None
    ]
    phase_end_times = [_parse_timestamp(event.end_timestamp) for event in phases]
    all_times = proposal_times + phase_start_times + phase_end_times
    min_time = min(all_times)
    max_time = max(all_times)
    total_seconds = max((max_time - min_time).total_seconds(), 1.0)

    color_palette = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    ]
    known_sender_colors = {
        node_id: color_palette[node_id % len(color_palette)]
        for node_id in selected_nodes
    }
    unknown_sender_color = "#6c757d"

    left_margin = 240
    right_margin = 60
    top_margin = 115
    bottom_margin = 80
    panel_height = 225 if annotate else 170
    width = 2400
    height = top_margin + bottom_margin + panel_height * len(selected_nodes)
    usable_width = width - left_margin - right_margin
    row_spacing = 28

    def x_for(dt: datetime) -> float:
        seconds = (dt - min_time).total_seconds()
        return left_margin + (seconds / total_seconds) * usable_width

    svg: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
        '<style>',
        "text { font-family: Arial, sans-serif; fill: #1f2933; }",
        ".small { font-size: 11px; }",
        ".tiny { font-size: 10px; }",
        ".panel-title { font-size: 14px; font-weight: 700; }",
        ".main-title { font-size: 20px; font-weight: 700; }",
        ".legend { font-size: 12px; }",
        "</style>",
    ]

    chart_title = title or "Validator proposal timeline with establish phase boundaries"
    svg.append(
        f'<text x="{width / 2:.1f}" y="28" text-anchor="middle" class="main-title">'
        f"{html.escape(chart_title)}</text>"
    )
    subtitle = (
        f"{html.escape(str(parsed['validator_log_dir']))} | "
        f"{html.escape(_timestamp_tail(min_time.strftime('%Y-%b-%d %H:%M:%S.%f UTC')) or '')}"
        f" -> "
        f"{html.escape(_timestamp_tail(max_time.strftime('%Y-%b-%d %H:%M:%S.%f UTC')) or '')}"
    )
    svg.append(
        f'<text x="{width / 2:.1f}" y="50" text-anchor="middle" class="small">{subtitle}</text>'
    )

    legend_y = 76
    legend_x = left_margin
    legend_items = []
    for node_id in selected_nodes:
        legend_items.append((known_sender_colors[node_id], f"proposal from node{node_id}"))
    legend_items.extend(
        [
            ("#000000", "bow-out proposal (cross marker)"),
            ("#f4a261", "establish phase window"),
            ("#111111", "establish end / accept (diamond)"),
        ]
    )
    cursor_x = legend_x
    for color, label in legend_items:
        if "bow-out" in label:
            svg.append(
                f'<line x1="{cursor_x}" y1="{legend_y - 5}" x2="{cursor_x + 10}" y2="{legend_y + 5}" '
                f'stroke="{color}" stroke-width="1.8"/>'
            )
            svg.append(
                f'<line x1="{cursor_x}" y1="{legend_y + 5}" x2="{cursor_x + 10}" y2="{legend_y - 5}" '
                f'stroke="{color}" stroke-width="1.8"/>'
            )
        elif "window" in label:
            svg.append(
                f'<rect x="{cursor_x}" y="{legend_y - 7}" width="12" height="12" '
                f'fill="{color}" fill-opacity="0.28" stroke="{color}" stroke-opacity="0.35"/>'
            )
        elif "diamond" in label:
            points = [
                (cursor_x + 6, legend_y - 7),
                (cursor_x + 12, legend_y - 1),
                (cursor_x + 6, legend_y + 5),
                (cursor_x, legend_y - 1),
            ]
            point_attr = " ".join(f"{x},{y}" for x, y in points)
            svg.append(
                f'<polygon points="{point_attr}" fill="{color}" stroke="{color}" stroke-width="1.2"/>'
            )
        else:
            svg.append(
                f'<circle cx="{cursor_x + 6}" cy="{legend_y - 1}" r="5" fill="{color}" stroke="{color}"/>'
            )
        svg.append(
            f'<text x="{cursor_x + 18}" y="{legend_y + 3}" class="legend">{html.escape(label)}</text>'
        )
        cursor_x += 18 + len(label) * 7.2

    tick_count = 8
    tick_times = [
        min_time + (max_time - min_time) * i / max(tick_count - 1, 1)
        for i in range(tick_count)
    ]

    for tick_dt in tick_times:
        x = x_for(tick_dt)
        svg.append(
            f'<line x1="{x:.2f}" y1="{top_margin - 8}" x2="{x:.2f}" y2="{height - bottom_margin + 6}" '
            'stroke="#d0d7de" stroke-dasharray="4 4" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="{x:.2f}" y="{height - 22}" text-anchor="middle" class="small">'
            f"{html.escape(tick_dt.strftime('%H:%M:%S'))}</text>"
        )

    for panel_idx, receiver_node in enumerate(selected_nodes):
        panel_top = top_margin + panel_idx * panel_height
        panel_bottom = panel_top + panel_height - 26
        node_proposals = [event for event in proposals if event.receiver_node == receiver_node]
        node_phases = [event for event in phases if event.receiver_node == receiver_node]
        sender_keys, y_positions = _build_sender_positions(node_proposals)
        phase_y = len(sender_keys)

        def y_for(row_idx: int) -> float:
            return panel_top + 26 + row_idx * row_spacing

        svg.append(
            f'<rect x="20" y="{panel_top - 14}" width="{width - 40}" height="{panel_height - 8}" '
            'fill="none" stroke="#e5e7eb" stroke-width="1"/>'
        )
        svg.append(
            f'<text x="24" y="{panel_top}" class="panel-title">{html.escape(f"node{receiver_node}")}</text>'
        )

        for key in sender_keys:
            row_idx = y_positions[key]
            y = y_for(row_idx)
            if key.startswith("node:"):
                label = f"from node{key.split(':', 1)[1]}"
            elif key.startswith("overlay:"):
                label = f"from {key.split(':', 1)[1][:8]}"
            else:
                label = key
            svg.append(
                f'<text x="{left_margin - 10}" y="{y + 4:.2f}" text-anchor="end" class="small">'
                f"{html.escape(label)}</text>"
            )
            svg.append(
                f'<line x1="{left_margin}" y1="{y:.2f}" x2="{width - right_margin}" y2="{y:.2f}" '
                'stroke="#f3f4f6" stroke-width="1"/>'
            )

        phase_line_y = y_for(phase_y)
        svg.append(
            f'<text x="{left_margin - 10}" y="{phase_line_y + 4:.2f}" text-anchor="end" class="small">'
            "establish end</text>"
        )

        for phase_idx, phase in enumerate(node_phases):
            if phase.start_timestamp is not None:
                start_dt = _parse_timestamp(phase.start_timestamp)
                end_dt = _parse_timestamp(phase.end_timestamp)
                x1 = x_for(start_dt)
                x2 = x_for(end_dt)
                svg.append(
                    f'<rect x="{x1:.2f}" y="{panel_top + 10}" width="{max(x2 - x1, 1):.2f}" '
                    f'height="{panel_height - 42}" fill="#f4a261" fill-opacity="0.10" '
                    'stroke="#f4a261" stroke-opacity="0.25" stroke-width="1"/>'
                )

            end_dt = _parse_timestamp(phase.end_timestamp)
            x = x_for(end_dt)
            diamond_points = [
                (x, phase_line_y - 8),
                (x + 7, phase_line_y - 1),
                (x, phase_line_y + 6),
                (x - 7, phase_line_y - 1),
            ]
            point_attr = " ".join(f"{px:.2f},{py:.2f}" for px, py in diamond_points)
            svg.append(
                f'<polygon points="{point_attr}" fill="#111111" stroke="#111111" stroke-width="1.2"/>'
            )
            if annotate:
                fragments = []
                if phase.prev_seq is not None:
                    fragments.append(f"prev#{phase.prev_seq}")
                if phase.built_ledger:
                    fragments.append(f"built={_hash_short(phase.built_ledger)}")
                if phase.consensus_close_time is not None:
                    fragments.append(f"ct={phase.consensus_close_time}")
                if phase.participants is not None:
                    fragments.append(f"p={phase.participants}")
                label = "accept"
                if fragments:
                    label += " " + " ".join(fragments)
                label += f" @{_timestamp_tail(phase.end_timestamp, with_fraction=True)}"
                label_y = phase_line_y - 12 if phase_idx % 2 == 0 else phase_line_y + 20
                svg.append(
                    f'<text x="{x + 8:.2f}" y="{label_y:.2f}" class="tiny">'
                    f"{html.escape(label)}</text>"
                )

        for prop_idx, event in enumerate(node_proposals):
            key = _sender_key(event)
            row_idx = y_positions[key]
            y = y_for(row_idx)
            x = x_for(_parse_timestamp(event.timestamp))
            color = _sender_color(event.sender_node, known_sender_colors, unknown_sender_color)
            if event.is_bow_out:
                svg.append(
                    f'<line x1="{x - 5:.2f}" y1="{y - 5:.2f}" x2="{x + 5:.2f}" y2="{y + 5:.2f}" '
                    f'stroke="{color}" stroke-width="1.8"/>'
                )
                svg.append(
                    f'<line x1="{x - 5:.2f}" y1="{y + 5:.2f}" x2="{x + 5:.2f}" y2="{y - 5:.2f}" '
                    f'stroke="{color}" stroke-width="1.8"/>'
                )
            else:
                svg.append(
                    f'<circle cx="{x:.2f}" cy="{y:.2f}" r="4.5" fill="{color}" stroke="{color}"/>'
                )

            if annotate:
                label = (
                    f"{event.sender_label} p{event.proposal_seq} "
                    f"prev={_hash_short(event.previous_ledger)} "
                    f"pos={_hash_short(event.position)} "
                    f"ct={_timestamp_tail(event.close_time)}"
                )
                label_y = y - 10 if prop_idx % 2 == 0 else y + 16
                svg.append(
                    f'<text x="{x + 7:.2f}" y="{label_y:.2f}" class="tiny">'
                    f"{html.escape(label)}</text>"
                )

        svg.append(
            f'<line x1="{left_margin}" y1="{panel_bottom:.2f}" x2="{width - right_margin}" y2="{panel_bottom:.2f}" '
            'stroke="#111827" stroke-width="1"/>'
        )

    svg.append(
        f'<text x="{width / 2:.1f}" y="{height - 6}" text-anchor="middle" class="small">'
        "UTC wall-clock time</text>"
    )
    svg.append("</svg>")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(svg) + "\n", encoding="utf-8")
    return out_path


def plot_proposal_timelines(
    parsed: dict[str, Any],
    out_path: str | Path,
    nodes: list[int] | None = None,
    annotate: bool = True,
    title: str | None = None,
) -> Path:
    selected_nodes = _parse_node_selection(nodes, parsed)
    out = Path(out_path).expanduser().resolve()

    if plt is None or mdates is None or Line2D is None:
        if out.suffix.lower() == ".svg":
            return _write_timeline_svg(
                parsed,
                out,
                selected_nodes=selected_nodes,
                annotate=annotate,
                title=title,
            )
        raise RuntimeError(
            "matplotlib is not available in this environment; "
            "use an .svg output path for the built-in SVG renderer"
        )

    proposals, phases = _collect_plot_events(parsed, selected_nodes)

    if not proposals and not phases:
        raise ValueError("No proposal or establish events available to plot")

    proposal_times = [_parse_timestamp(event.timestamp) for event in proposals]
    phase_start_times = [
        _parse_timestamp(event.start_timestamp)
        for event in phases
        if event.start_timestamp is not None
    ]
    phase_end_times = [_parse_timestamp(event.end_timestamp) for event in phases]
    all_times = proposal_times + phase_start_times + phase_end_times
    min_time = min(all_times)
    max_time = max(all_times)

    color_palette = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    ]
    known_sender_colors = {
        node_id: color_palette[node_id % len(color_palette)]
        for node_id in selected_nodes
    }
    unknown_sender_color = "#6c757d"

    fig, axes = plt.subplots(
        len(selected_nodes),
        1,
        figsize=(24, max(3.5 * len(selected_nodes), 7)),
        sharex=True,
        squeeze=False,
    )
    axes = axes.flatten()

    for ax, receiver_node in zip(axes, selected_nodes):
        node_proposals = [event for event in proposals if event.receiver_node == receiver_node]
        node_phases = [event for event in phases if event.receiver_node == receiver_node]
        sender_keys: list[str] = []
        for event in node_proposals:
            sender_key = (
                f"node:{event.sender_node}"
                if event.sender_node is not None
                else f"overlay:{event.sender_overlay_id}"
            )
            if sender_key not in sender_keys:
                sender_keys.append(sender_key)

        if not sender_keys:
            sender_keys.append("phase")

        y_positions = {key: idx for idx, key in enumerate(sender_keys)}
        phase_y = len(sender_keys)

        for phase_idx, phase in enumerate(node_phases):
            if phase.start_timestamp is not None:
                start_dt = _parse_timestamp(phase.start_timestamp)
                end_dt = _parse_timestamp(phase.end_timestamp)
                ax.axvspan(start_dt, end_dt, color="#f4a261", alpha=0.08, zorder=0)

            end_dt = _parse_timestamp(phase.end_timestamp)
            ax.scatter(
                end_dt,
                phase_y,
                marker="D",
                s=26,
                color="black",
                zorder=4,
                rasterized=True,
            )
            if annotate:
                fragments = []
                if phase.prev_seq is not None:
                    fragments.append(f"prev#{phase.prev_seq}")
                if phase.built_ledger:
                    fragments.append(f"built={_hash_short(phase.built_ledger)}")
                if phase.consensus_close_time is not None:
                    fragments.append(f"ct={phase.consensus_close_time}")
                if phase.participants is not None:
                    fragments.append(f"p={phase.participants}")
                label = "accept"
                if fragments:
                    label += " " + " ".join(fragments)
                label += f" @{_timestamp_tail(phase.end_timestamp, with_fraction=True)}"
                ax.annotate(
                    label,
                    (end_dt, phase_y),
                    xytext=(6, 9 if phase_idx % 2 == 0 else -11),
                    textcoords="offset points",
                    fontsize=6.1,
                    rotation=18,
                    va="bottom" if phase_idx % 2 == 0 else "top",
                    ha="left",
                )

        for prop_idx, event in enumerate(node_proposals):
            sender_key = (
                f"node:{event.sender_node}"
                if event.sender_node is not None
                else f"overlay:{event.sender_overlay_id}"
            )
            event_dt = _parse_timestamp(event.timestamp)
            y = y_positions[sender_key]
            color = _sender_color(
                event.sender_node,
                known_sender_colors,
                unknown_sender_color,
            )
            marker = "x" if event.is_bow_out else "o"
            ax.scatter(
                event_dt,
                y,
                marker=marker,
                s=20,
                color=color,
                linewidths=0.7,
                zorder=3,
                rasterized=True,
            )

            if annotate:
                label = (
                    f"{event.sender_label} p{event.proposal_seq} "
                    f"prev={_hash_short(event.previous_ledger)} "
                    f"pos={_hash_short(event.position)} "
                    f"ct={_timestamp_tail(event.close_time)}"
                )
                ax.annotate(
                    label,
                    (event_dt, y),
                    xytext=(5, 8 if prop_idx % 2 == 0 else -10),
                    textcoords="offset points",
                    fontsize=5.7,
                    rotation=18,
                    va="bottom" if prop_idx % 2 == 0 else "top",
                    ha="left",
                )

        y_ticks = list(y_positions.values()) + [phase_y]
        y_labels = []
        for key in sender_keys:
            if key.startswith("node:"):
                y_labels.append(f"from node{key.split(':', 1)[1]}")
            elif key.startswith("overlay:"):
                y_labels.append(f"from {key.split(':', 1)[1][:8]}")
            else:
                y_labels.append(key)
        y_labels.append("establish end")

        ax.set_yticks(y_ticks)
        ax.set_yticklabels(y_labels, fontsize=8)
        ax.set_ylim(-0.8, phase_y + 0.9)
        ax.set_ylabel(f"node{receiver_node}", fontsize=10)
        ax.grid(True, axis="x", linestyle="--", alpha=0.35)
        ax.grid(True, axis="y", linestyle=":", alpha=0.15)

    axes[-1].set_xlim(min_time, max_time)
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    axes[-1].xaxis.set_major_locator(mdates.AutoDateLocator(minticks=6, maxticks=12))
    axes[-1].set_xlabel("UTC wall-clock time")

    legend_handles: list[Any] = []
    for node_id in selected_nodes:
        legend_handles.append(
            Line2D(
                [0],
                [0],
                marker="o",
                color="w",
                label=f"proposal from node{node_id}",
                markerfacecolor=known_sender_colors[node_id],
                markersize=5,
            )
        )
    legend_handles.extend(
        [
            Line2D(
                [0],
                [0],
                marker="x",
                color="black",
                label="bow-out proposal",
                linestyle="None",
                markersize=5,
            ),
            Line2D(
                [0],
                [0],
                marker="D",
                color="black",
                label="establish end / accept",
                linestyle="None",
                markersize=5,
            ),
            Line2D(
                [0],
                [0],
                color="#f4a261",
                linewidth=4,
                alpha=0.28,
                label="establish phase window",
            ),
        ]
    )

    fig.legend(
        handles=legend_handles,
        loc="upper center",
        ncol=min(len(legend_handles), 4),
        frameon=False,
        bbox_to_anchor=(0.5, 0.995),
    )
    fig.suptitle(
        title
        or "Validator proposal timeline with establish phase boundaries",
        y=0.999,
        fontsize=14,
    )
    fig.autofmt_xdate(rotation=20)
    fig.tight_layout(rect=(0, 0, 1, 0.965))

    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return out


def _latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(ch, ch) for ch in value)


def _format_hash_ref(hash_value: str | None, seq: int | None = None) -> str:
    if not hash_value:
        return "-"
    if seq is None:
        return _hash_short(hash_value)
    return f"{_hash_short(hash_value)} / s{seq}"


def _format_table_time(timestamp: str | None) -> str:
    if not timestamp:
        return "-"

    match = re.search(r" (\d{2}:\d{2}:\d{2})(?:\.(\d+))?", timestamp)
    if not match:
        return timestamp

    whole = match.group(1)
    fraction = match.group(2)
    if not fraction:
        return whole

    return f"{whole}.{fraction[:2]}"


def _format_yes_no_unknown(value: bool | None) -> str:
    if value is None:
        return "-"
    return "yes" if value else "no"


def _format_detail_status(status: str) -> str:
    mapping = {
        "compatible_evicted_before_open": "compatible earlier, but evicted before open",
        "replay_current": "compatible; replayed into current round",
        "replayed_then_superseded": "compatible earlier; later superseded",
        "other_prev": "different parent ledger",
        "rejected_after_open_incompatible_prev": "after open, rejected: different parent ledger",
    }
    return mapping.get(status, status.replace("_", " "))


def _build_table_rows_for_node(node_data: dict[str, Any]) -> list[dict[str, Any]]:
    proposals = [ProposalEvent(**event) for event in node_data["proposals"]]
    phases = [EstablishPhaseEvent(**event) for event in node_data["establish_phases"]]
    rows: list[dict[str, Any]] = []

    for phase in phases:
        if phase.start_timestamp is not None:
            rows.append(
                {
                    "timestamp": phase.start_timestamp,
                    "event_rank": 0,
                    "event": "establish start",
                    "ledger_seq": phase.working_ledger_seq,
                    "sender": "-",
                    "prev": _format_hash_ref(phase.prev_ledger, phase.prev_seq),
                    "value": "-",
                    "close": "-",
                    "notes": "entered establish phase",
                    "row_color": "blue!6",
                }
            )

        notes = []
        if phase.participants is not None:
            notes.append(f"participants={phase.participants}")
        if phase.duration_ms is not None:
            notes.append(f"duration={phase.duration_ms:.0f}ms")
        if phase.on_accept_duration_s is not None:
            notes.append(f"onAccept={phase.on_accept_duration_s:.3f}s")
        if phase.tx_set:
            notes.append(f"txset={_hash_short(phase.tx_set)}")

        rows.append(
            {
                "timestamp": phase.end_timestamp,
                "event_rank": 2,
                "event": "accept",
                "ledger_seq": phase.working_ledger_seq,
                "sender": "-",
                "prev": _format_hash_ref(phase.prev_ledger, phase.prev_seq),
                "value": _format_hash_ref(phase.built_ledger, phase.built_seq),
                "close": "-"
                if phase.consensus_close_time is None
                else str(phase.consensus_close_time),
                "notes": "; ".join(notes) if notes else "-",
                "row_color": "orange!12",
            }
        )

    for proposal in proposals:
        notes = [f"proposal_seq={proposal.proposal_seq}"]
        if proposal.is_bow_out:
            notes.append("bow_out=yes")
        proposal_now = _format_table_time(proposal.now)
        if proposal_now != "-":
            notes.append(f"proposal_now={proposal_now}")

        rows.append(
            {
                "timestamp": proposal.timestamp,
                "event_rank": 1,
                "event": "proposal",
                "ledger_seq": proposal.working_ledger_seq,
                "sender": proposal.sender_label,
                "prev": _format_hash_ref(
                    proposal.previous_ledger, proposal.previous_ledger_seq
                ),
                "value": f"pos={_hash_short(proposal.position)}",
                "close": _format_table_time(proposal.close_time),
                "notes": "; ".join(notes),
                "row_color": None,
            }
        )

    rows.sort(
        key=lambda row: (
            _parse_timestamp(row["timestamp"]),
            row["event_rank"],
            row["event"],
        )
    )
    return rows


def write_sequence_report_latex(
    report: dict[str, Any],
    out_path: str | Path,
    title: str | None = None,
) -> Path:
    context = report["context"]
    summary_rows = report["summary_rows"]
    detail_rows = report["detail_rows"]

    out = Path(out_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        r"\documentclass[10pt]{article}",
        r"\usepackage[margin=0.45in]{geometry}",
        r"\usepackage{longtable}",
        r"\usepackage{booktabs}",
        r"\usepackage{array}",
        r"\usepackage[table]{xcolor}",
        r"\usepackage{pdflscape}",
        r"\setlength{\LTleft}{0pt}",
        r"\setlength{\LTright}{0pt}",
        r"\renewcommand{\arraystretch}{1.12}",
        r"\newcolumntype{L}[1]{>{\raggedright\arraybackslash}p{#1}}",
        r"\begin{document}",
        r"\begin{center}",
        r"{\Large\bfseries "
        + _latex_escape(
            title
            or f"node{context['receiver_node']} working seq {context['working_seq']} proposal report"
        )
        + r"}\\[4pt]",
        r"\small Receiver: node"
        + str(context["receiver_node"])
        + r"\quad Working seq: "
        + str(context["working_seq"])
        + r"\quad Prev ledger: \texttt{"
        + _latex_escape(_format_hash_ref(context["prev_ledger"], context["prev_seq"]))
        + r"}\\",
        r"\small Open at line "
        + str(context["start_line_no"])
        + r" @ "
        + _latex_escape(_format_table_time(context["start_timestamp"]))
        + r"\quad replayed peer positions="
        + str(context["replayed_peer_positions"])
        + r"\quad prevProposers="
        + str(context["prev_proposers"]),
        r"\end{center}",
        r"\small",
        r"\section*{Round-Start Summary}",
        r"\begin{landscape}",
        r"\begin{longtable}{L{1.2cm} L{1.6cm} L{1.7cm} L{1.5cm} L{1.8cm} L{1.8cm} L{1.8cm} L{6.4cm}}",
        r"\toprule",
        r"From & Recv before open & Compat in last10 & Replayed at open & Fresh at first update & Replay close time & Replay prop time & Result \\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        r"From & Recv before open & Compat in last10 & Replayed at open & Fresh at first update & Replay close time & Replay prop time & Result \\",
        r"\midrule",
        r"\endhead",
        r"\bottomrule",
        r"\endfoot",
    ]

    for row in summary_rows:
        replayed_at_open = row["replay_current_line"] is not None
        fresh_at_first_update = (
            None
            if row["replay_current_line"] is None
            else not bool(row["stale_at_first_update"])
        )

        lines.append(
            " & ".join(
                [
                    _latex_escape(str(row["proposer"])),
                    _latex_escape(str(row["total_before_open"])),
                    _latex_escape(str(row["compatible_in_last10"])),
                    _latex_escape(_format_yes_no_unknown(replayed_at_open)),
                    _latex_escape(_format_yes_no_unknown(fresh_at_first_update)),
                    _latex_escape(_format_table_time(row["replay_current_close_time"])),
                    _latex_escape(_format_table_time(row["replay_current_now"])),
                    _latex_escape(str(row["status"])),
                ]
            )
            + r" \\"
        )

    lines.extend(
        [
            r"\end{longtable}",
            r"\vspace{4pt}",
            r"{\footnotesize "
            r"\textbf{Column meanings.} "
            r"\textit{Parent}: the previous ledger this proposal builds on. "
            r"\textit{proposal\_seq}: rippled's per-peer proposal sequence number within consensus. "
            r"\textit{Proposal hash}: the proposal position / tx-set hash. "
            r"\textit{Proposal time}: the proposal's own timestamp used for freshness checks. "
            r"\textit{Result}: how this proposal affected node"
            + str(context["receiver_node"])
            + r" in this round. "
            r"Raw line numbers and extra debug flags remain in the CSV/JSON outputs.\par}",
            r"\section*{Chronological Proposal Table}",
            r"\begin{longtable}{L{1.6cm} L{1.1cm} L{2.0cm} L{0.8cm} L{1.5cm} L{1.5cm} L{1.6cm} L{6.6cm}}",
            r"\toprule",
            r"Time & From & Parent & proposal\_seq & Proposal hash & Close time & Proposal time & Result \\",
            r"\midrule",
            r"\endfirsthead",
            r"\toprule",
            r"Time & From & Parent & proposal\_seq & Proposal hash & Close time & Proposal time & Result \\",
            r"\midrule",
            r"\endhead",
            r"\bottomrule",
            r"\endfoot",
        ]
    )

    for row in detail_rows:
        row_color = None
        if row["current_after_replay"]:
            row_color = "green!10"
        elif row["status"] == "compatible_evicted_before_open":
            row_color = "red!8"
        elif row["stage"] == "after_open_before_first_update":
            row_color = "blue!6"
        if row_color:
            lines.append(r"\rowcolor{" + row_color + r"}")

        lines.append(
            " & ".join(
                [
                    _latex_escape(_format_table_time(row["timestamp"])),
                    _latex_escape(str(row["proposer"])),
                    r"\texttt{"
                    + _latex_escape(
                        _format_hash_ref(row["previous_ledger"], row["previous_ledger_seq"])
                    )
                    + r"}",
                    _latex_escape(str(row["proposal_seq"])),
                    r"\texttt{" + _latex_escape(_hash_short(row["position"])) + r"}",
                    r"\texttt{" + _latex_escape(_format_table_time(row["close_time"])) + r"}",
                    r"\texttt{" + _latex_escape(_format_table_time(row["proposal_now"])) + r"}",
                    _latex_escape(_format_detail_status(str(row["status"]))),
                ]
            )
            + r" \\"
        )

    lines.extend(
        [
            r"\end{longtable}",
            r"\end{landscape}",
            r"\end{document}",
        ]
    )

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def write_table_latex(
    parsed: dict[str, Any],
    out_path: str | Path,
    nodes: list[int] | None = None,
    title: str | None = None,
) -> Path:
    selected_nodes = _parse_node_selection(nodes, parsed)
    out = Path(out_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    lines = [
        r"\documentclass[10pt]{article}",
        r"\usepackage[margin=0.45in]{geometry}",
        r"\usepackage{longtable}",
        r"\usepackage{booktabs}",
        r"\usepackage{array}",
        r"\usepackage[table]{xcolor}",
        r"\usepackage{pdflscape}",
        r"\setlength{\LTleft}{0pt}",
        r"\setlength{\LTright}{0pt}",
        r"\renewcommand{\arraystretch}{1.12}",
        r"\newcolumntype{L}[1]{>{\raggedright\arraybackslash}p{#1}}",
        r"\begin{document}",
        r"\begin{center}",
        r"{\Large\bfseries "
        + _latex_escape(title or "Validator proposal tables")
        + r"}\\[4pt]",
        r"\small Source: "
        + _latex_escape(str(parsed["validator_log_dir"])),
        r"\end{center}",
        r"\small",
    ]

    header = (
        r"Time (UTC) & Event & Seq & Sender & Prev & Hash / Pos & Close / CT & Notes \\"
    )
    colspec = r"L{2.2cm} L{1.9cm} L{0.9cm} L{1.2cm} L{2.1cm} L{2.2cm} L{1.8cm} L{8.6cm}"

    for receiver_node in selected_nodes:
        rows = _build_table_rows_for_node(parsed["nodes"][receiver_node])
        lines.extend(
            [
                r"\clearpage",
                r"\begin{landscape}",
                r"\section*{node" + str(receiver_node) + r"}",
                r"\begin{longtable}{" + colspec + r"}",
                r"\toprule",
                header,
                r"\midrule",
                r"\endfirsthead",
                r"\toprule",
                header,
                r"\midrule",
                r"\endhead",
                r"\bottomrule",
                r"\endfoot",
            ]
        )

        current_seq: int | None = None
        for row in rows:
            row_seq = row["ledger_seq"]
            if row_seq is not None and row_seq != current_seq:
                current_seq = row_seq
                lines.append(r"\rowcolor{black!8}")
                lines.append(
                    r"\multicolumn{8}{l}{\textbf{Ledger seq "
                    + str(row_seq)
                    + r"}} \\"
                )

            if row["row_color"]:
                lines.append(r"\rowcolor{" + row["row_color"] + r"}")

            cells = [
                _latex_escape(_format_table_time(row["timestamp"])),
                _latex_escape(str(row["event"])),
                _latex_escape("-" if row_seq is None else str(row_seq)),
                _latex_escape(str(row["sender"])),
                r"\texttt{" + _latex_escape(str(row["prev"])) + r"}",
                r"\texttt{" + _latex_escape(str(row["value"])) + r"}",
                r"\texttt{" + _latex_escape(str(row["close"])) + r"}",
                _latex_escape(str(row["notes"])),
            ]
            lines.append(" & ".join(cells) + r" \\")

        lines.extend(
            [
                r"\end{longtable}",
                r"\end{landscape}",
            ]
        )

    lines.append(r"\end{document}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def compile_latex_pdf(latex_path: str | Path, pdf_out: str | Path | None = None) -> Path:
    tex_path = Path(latex_path).expanduser().resolve()
    workdir = tex_path.parent
    pdf_path = workdir / f"{tex_path.stem}.pdf"

    cmd = [
        "pdflatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        "-file-line-error",
        tex_path.name,
    ]

    for _ in range(2):
        result = subprocess.run(
            cmd,
            cwd=workdir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            tail = "\n".join(result.stdout.splitlines()[-40:])
            raise RuntimeError(f"pdflatex failed for {tex_path}:\n{tail}")

    if not pdf_path.exists():
        raise FileNotFoundError(f"Expected compiled PDF at {pdf_path}")

    if pdf_out is None:
        return pdf_path

    out = Path(pdf_out).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out != pdf_path:
        out.write_bytes(pdf_path.read_bytes())
    return out


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Parse received peer proposals from validator debug logs and optionally "
            "render a per-node proposal timeline."
        )
    )
    parser.add_argument(
        "log_dir",
        nargs="?",
        type=Path,
        default=Path("/data/home/lli21/rocket/evo/run_cache/G258T3"),
        help=(
            "Saved run dir, iteration dir, validator_live_logs dir, or one "
            "validator_*_debug.txt file."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Optional JSON output path. Prints JSON to stdout when omitted.",
    )
    parser.add_argument(
        "--csv-out",
        type=Path,
        default=None,
        help="Optional flattened CSV output path.",
    )
    parser.add_argument(
        "--plot-out",
        type=Path,
        default=None,
        help="Optional SVG/PNG/PDF plot output path.",
    )
    parser.add_argument(
        "--nodes",
        type=int,
        nargs="*",
        default=None,
        help="Optional receiver node ids to include in generated plots/tables.",
    )
    parser.add_argument(
        "--table-tex-out",
        type=Path,
        default=None,
        help="Optional LaTeX longtable document output path.",
    )
    parser.add_argument(
        "--table-pdf-out",
        type=Path,
        default=None,
        help="Optional PDF compiled from the generated LaTeX table document.",
    )
    parser.add_argument(
        "--no-annotations",
        action="store_true",
        help="Disable text annotations in the generated timeline plot.",
    )
    parser.add_argument(
        "--title",
        type=str,
        default=None,
        help="Optional title override for the generated plot.",
    )
    parser.add_argument(
        "--sequence-report-node",
        type=int,
        default=None,
        help="Receiver node id for a focused round report, e.g. 2 for node2.",
    )
    parser.add_argument(
        "--sequence-report-seq",
        type=int,
        default=None,
        help="Working ledger sequence for the focused round report, e.g. 6.",
    )
    parser.add_argument(
        "--sequence-report-json-out",
        type=Path,
        default=None,
        help="Optional JSON output path for the focused round report.",
    )
    parser.add_argument(
        "--sequence-report-summary-csv-out",
        type=Path,
        default=None,
        help="Optional CSV output path for the focused round summary table.",
    )
    parser.add_argument(
        "--sequence-report-detail-csv-out",
        type=Path,
        default=None,
        help="Optional CSV output path for the focused round proposal-detail table.",
    )
    parser.add_argument(
        "--sequence-report-tex-out",
        type=Path,
        default=None,
        help="Optional LaTeX output path for the focused round report.",
    )
    parser.add_argument(
        "--sequence-report-pdf-out",
        type=Path,
        default=None,
        help="Optional PDF output path for the focused round report.",
    )
    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    parsed = parse_proposals(args.log_dir)
    sequence_report: dict[str, Any] | None = None

    table_tex_path: Path | None = args.table_tex_out
    if args.table_pdf_out is not None and table_tex_path is None:
        table_tex_path = args.table_pdf_out.with_suffix(".tex")

    sequence_report_tex_path: Path | None = args.sequence_report_tex_out
    if args.sequence_report_pdf_out is not None and sequence_report_tex_path is None:
        sequence_report_tex_path = args.sequence_report_pdf_out.with_suffix(".tex")

    if (args.sequence_report_node is None) != (args.sequence_report_seq is None):
        raise ValueError(
            "--sequence-report-node and --sequence-report-seq must be provided together"
        )

    if args.plot_out is not None:
        plot_path = plot_proposal_timelines(
            parsed,
            args.plot_out,
            nodes=args.nodes,
            annotate=not args.no_annotations,
            title=args.title,
        )
        print(f"Wrote proposal timeline plot to {plot_path}")

    if args.csv_out is not None:
        csv_path = write_events_csv(parsed, args.csv_out)
        print(f"Wrote flattened proposal events CSV to {csv_path}")

    if table_tex_path is not None:
        written_tex_path = write_table_latex(
            parsed,
            table_tex_path,
            nodes=args.nodes,
            title=args.title,
        )
        print(f"Wrote LaTeX proposal tables to {written_tex_path}")
    else:
        written_tex_path = None

    if args.table_pdf_out is not None:
        if written_tex_path is None:
            raise RuntimeError("table_tex_path should have been created")
        pdf_path = compile_latex_pdf(written_tex_path, args.table_pdf_out)
        print(f"Wrote PDF proposal tables to {pdf_path}")

    if args.sequence_report_node is not None and args.sequence_report_seq is not None:
        sequence_report = build_sequence_report(
            parsed,
            receiver_node=args.sequence_report_node,
            working_seq=args.sequence_report_seq,
        )

        if args.sequence_report_json_out is not None:
            json_path = write_sequence_report_json(
                sequence_report, args.sequence_report_json_out
            )
            print(f"Wrote sequence report JSON to {json_path}")

        if (
            args.sequence_report_summary_csv_out is not None
            or args.sequence_report_detail_csv_out is not None
        ):
            if (
                args.sequence_report_summary_csv_out is None
                or args.sequence_report_detail_csv_out is None
            ):
                raise ValueError(
                    "--sequence-report-summary-csv-out and "
                    "--sequence-report-detail-csv-out must be provided together"
                )
            summary_csv_path, detail_csv_path = write_sequence_report_csvs(
                sequence_report,
                args.sequence_report_summary_csv_out,
                args.sequence_report_detail_csv_out,
            )
            print(f"Wrote sequence report summary CSV to {summary_csv_path}")
            print(f"Wrote sequence report detail CSV to {detail_csv_path}")

        if sequence_report_tex_path is not None:
            written_sequence_tex_path = write_sequence_report_latex(
                sequence_report,
                sequence_report_tex_path,
                title=args.title,
            )
            print(f"Wrote sequence report LaTeX to {written_sequence_tex_path}")
        else:
            written_sequence_tex_path = None

        if args.sequence_report_pdf_out is not None:
            if written_sequence_tex_path is None:
                raise RuntimeError("sequence_report_tex_path should have been created")
            sequence_pdf_path = compile_latex_pdf(
                written_sequence_tex_path, args.sequence_report_pdf_out
            )
            print(f"Wrote sequence report PDF to {sequence_pdf_path}")

    if args.out is not None:
        out_path = args.out.expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(parsed, indent=2, sort_keys=True), encoding="utf-8")
        print(f"Wrote parsed proposal events to {out_path}")
    elif (
        args.plot_out is None
        and args.csv_out is None
        and args.table_tex_out is None
        and args.table_pdf_out is None
        and args.sequence_report_json_out is None
        and args.sequence_report_summary_csv_out is None
        and args.sequence_report_detail_csv_out is None
        and args.sequence_report_tex_out is None
        and args.sequence_report_pdf_out is None
    ):
        if sequence_report is not None:
            print(json.dumps(sequence_report, indent=2, sort_keys=True))
        else:
            print(json.dumps(parsed, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
