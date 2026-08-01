from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .cases import resolve_iteration_dir, resolve_live_logs_dir
from .utils import analysis_dir


TIMESTAMP_RE = re.compile(
    r"^(\d{4}-[A-Za-z]{3}-\d{2} \d{2}:\d{2}:\d{2}\.\d+ UTC)\s"
)
VALIDATOR_LOG_RE = re.compile(r"validator_(\d+)_log\.txt$")
START_ROUND_RE = re.compile(
    r"startRoundInternal transitioned to ConsensusPhase::open, "
    r"previous ledgerID: ([A-F0-9]+), seq: (\d+)\. "
    r"number of peer proposals,previous proposers: (\d+),(\d+)\."
)
CLOSE_LEDGER_RE = re.compile(
    r"prevRoundTime: (\d+)ms, .*?closeLedger transitioned to ConsensusPhase::establish"
)
CREATE_DISPUTES_RE = re.compile(r"createDisputes ([A-F0-9]+) to ([A-F0-9]+)")
PEER_VOTE_RE = re.compile(r"Peer ([A-F0-9]+) votes (YES|NO) on ([A-F0-9]+)")
PEER_NOW_VOTE_RE = re.compile(r"Peer ([A-F0-9]+) now votes (YES|NO) on ([A-F0-9]+)")
NO_CHANGE_RE = re.compile(
    r"No change \((YES|NO)\) on ([A-F0-9]+) : weight (-?\d+), "
    r"percent (\d+), round\(s\) with this vote: (\d+)"
)
WE_NOW_RE = re.compile(r"We now vote (YES|NO) on ([A-F0-9]+)")
JSON_VOTE_RE = re.compile(r"LedgerConsensus:DBG (\{.*\})$")
TIMER_RE = re.compile(r"ConsensusLogger Heartbeat Timer:")
CONVERGE_RE = re.compile(
    r"convergePercent_ (\d+) is based on round duration so far: (\d+)ms, "
    r"previous round duration: (\d+)ms, avMIN_CONSENSUS_TIME: (\d+)ms"
)
NEEDED_WEIGHT_RE = re.compile(r"neededWeight (\d+)|Proposers:\d+ nw:(\d+)")
CHECK_CONSENSUS_RE = re.compile(
    r"checkConsensus: prop=(\d+)/(\d+) agree=(\d+) validated=(\d+) time=(\d+)/(\d+)"
)
POSITION_CHANGE_RE = re.compile(r"Position change: CTime (\d+), tx ([A-F0-9]+)")
BUILDING_SET_RE = re.compile(r"Building canonical tx set: ([A-F0-9]+)")
BUILT_LEDGER_RE = re.compile(r"Built ledger #(\d+): ([A-F0-9]+)")

AV_MIN_ROUNDS = 2
AVALANCHE_CUTOFFS = {
    "init": {"time": 0, "pct": 50, "next": "mid"},
    "mid": {"time": 50, "pct": 65, "next": "late"},
    "late": {"time": 85, "pct": 70, "next": "stuck"},
    "stuck": {"time": 200, "pct": 95, "next": "stuck"},
}


@dataclass
class OpenRound:
    working_seq: int
    prev_ledger: str
    start_timestamp: str
    start_ms: int
    source_line: int
    current_peer_proposals: int
    previous_proposers: int


@dataclass
class PendingDispute:
    timestamp: str
    timestamp_ms: int
    source_line: int
    local_txset: str
    other_txset: str
    peer_votes: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class PendingVoteUpdate:
    timestamp: str
    timestamp_ms: int
    source_line: int
    tx: str
    action: str
    old_vote: str | None
    new_vote: str
    weight: int | None = None
    percent: int | None = None
    rounds_with_vote: int | None = None
    json_state: dict[str, Any] | None = None


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


def _timestamp_ms(timestamp: str) -> int:
    dt = _parse_timestamp(timestamp)
    return int(dt.timestamp() * 1000)


def _timestamp_us(timestamp: str) -> int:
    dt = _parse_timestamp(timestamp)
    return int(dt.timestamp() * 1_000_000)


def _timestamp(line: str) -> str | None:
    match = TIMESTAMP_RE.match(line)
    return None if match is None else match.group(1)


def _node_from_log(path: Path) -> int | None:
    match = VALIDATOR_LOG_RE.fullmatch(path.name)
    return None if match is None else int(match.group(1))


def _select_logs(case_dir: Path) -> dict[int, Path]:
    live_logs_dir = resolve_live_logs_dir(case_dir)
    out: dict[int, Path] = {}
    for path in sorted(live_logs_dir.glob("validator_*_log.txt")):
        node = _node_from_log(path)
        if node is not None:
            out[node] = path
    if out:
        return out

    validator_logs = resolve_iteration_dir(case_dir) / "validator_logs"
    for path in sorted(validator_logs.glob("*validator_*_log.txt")):
        match = re.search(r"validator_(\d+)_log\.txt$", path.name)
        if match:
            out[int(match.group(1))] = path
    return out


def _short(value: str | None) -> str:
    return "" if not value else value[:8]


def _overlay_node(overlay_map: dict[str, dict[str, Any]], overlay_id: str) -> int | None:
    mapped = overlay_map.get(overlay_id) or {}
    node = mapped.get("node")
    return None if node in ("", None) else int(node)


def _vote_to_bool(vote: str) -> bool:
    return vote.upper() == "YES"


def _compute_weight(yays: int, nays: int, our_vote: bool) -> int:
    return (yays * 100 + (100 if our_vote else 0)) // (yays + nays + 1)


def _dispute_required_pct(
    current_state: str,
    percent_time: int | None,
    current_rounds: int,
) -> tuple[int | None, str | None]:
    if percent_time is None:
        return None, None
    current = AVALANCHE_CUTOFFS[current_state]
    next_state = str(current["next"])
    if next_state != current_state and current_rounds >= AV_MIN_ROUNDS:
        next_cutoff = AVALANCHE_CUTOFFS[next_state]
        if percent_time >= int(next_cutoff["time"]):
            return int(next_cutoff["pct"]), next_state
    return int(current["pct"]), None


def _nearest_round(open_rounds: list[OpenRound], timestamp_ms: int, target_seq: int) -> OpenRound | None:
    candidates = [
        r for r in open_rounds if r.start_ms <= timestamp_ms
    ]
    if not candidates:
        return None
    active = max(candidates, key=lambda r: r.start_ms)
    return active if active.working_seq == target_seq else None


def _scan_consensus_logs(
    log_files: dict[int, Path],
    *,
    target_seq: int,
    target_tx: str,
    overlay_map: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    node_data: dict[int, dict[str, Any]] = {
        node: {
            "rounds": [],
            "establish": [],
            "disputes": [],
            "peer_vote_updates": [],
            "vote_updates": [],
            "position_changes": [],
            "built_ledgers": [],
        }
        for node in sorted(log_files)
    }

    for node, path in sorted(log_files.items()):
        active_rounds: list[OpenRound] = []
        dispute_state = {
            "avalanche_state": "init",
            "avalanche_counter": 0,
            "current_vote_counter": 0,
        }
        pending_dispute: PendingDispute | None = None
        pending_update: PendingVoteUpdate | None = None

        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        for line_no, line in enumerate(lines, start=1):
            ts = _timestamp(line)
            if not ts:
                continue
            ts_ms = _timestamp_ms(ts)

            start_match = START_ROUND_RE.search(line)
            if start_match:
                prev_seq = int(start_match.group(2))
                round_info = OpenRound(
                    working_seq=prev_seq + 1,
                    prev_ledger=start_match.group(1),
                    start_timestamp=ts,
                    start_ms=ts_ms,
                    source_line=line_no,
                    current_peer_proposals=int(start_match.group(3)),
                    previous_proposers=int(start_match.group(4)),
                )
                active_rounds.append(round_info)
                if round_info.working_seq == target_seq:
                    node_data[node]["rounds"].append(
                        {
                            "working_seq": round_info.working_seq,
                            "prev_ledger": round_info.prev_ledger,
                            "start_timestamp": ts,
                            "start_ms": ts_ms,
                            "current_peer_proposals": round_info.current_peer_proposals,
                            "previous_proposers": round_info.previous_proposers,
                            "source": f"{path.name}:{line_no}",
                        }
                    )
                continue

            close_match = CLOSE_LEDGER_RE.search(line)
            if close_match:
                active = _nearest_round(active_rounds, ts_ms, target_seq)
                if active is not None:
                    node_data[node]["establish"].append(
                        {
                            "working_seq": target_seq,
                            "timestamp": ts,
                            "time_ms": ts_ms,
                            "relative_to_round_start_ms": ts_ms - active.start_ms,
                            "prev_round_time_ms": int(close_match.group(1)),
                            "source": f"{path.name}:{line_no}",
                        }
                    )

            dispute_match = CREATE_DISPUTES_RE.search(line)
            if dispute_match:
                active = _nearest_round(active_rounds, ts_ms, target_seq)
                if active is not None:
                    pending_dispute = PendingDispute(
                        timestamp=ts,
                        timestamp_ms=ts_ms,
                        source_line=line_no,
                        local_txset=dispute_match.group(1),
                        other_txset=dispute_match.group(2),
                    )
                continue

            if pending_dispute is not None:
                peer_vote_match = PEER_VOTE_RE.search(line)
                if peer_vote_match and peer_vote_match.group(3) == target_tx:
                    overlay = peer_vote_match.group(1)
                    pending_dispute.peer_votes.append(
                        {
                            "overlay_id": overlay,
                            "node": _overlay_node(overlay_map, overlay),
                            "vote": peer_vote_match.group(2).lower(),
                        }
                    )
                    continue
                if "differences found" in line:
                    yes_nodes = sorted(
                        v["node"] for v in pending_dispute.peer_votes if v["vote"] == "yes" and v["node"] is not None
                    )
                    no_nodes = sorted(
                        v["node"] for v in pending_dispute.peer_votes if v["vote"] == "no" and v["node"] is not None
                    )
                    node_data[node]["disputes"].append(
                        {
                            "working_seq": target_seq,
                            "timestamp": pending_dispute.timestamp,
                            "time_ms": pending_dispute.timestamp_ms,
                            "local_txset": pending_dispute.local_txset,
                            "other_txset": pending_dispute.other_txset,
                            "target_tx": target_tx,
                            "peer_votes": pending_dispute.peer_votes,
                            "yes_nodes": yes_nodes,
                            "no_nodes": no_nodes,
                            "source": f"{path.name}:{pending_dispute.source_line}",
                        }
                    )
                    pending_dispute = None
                    continue

            peer_now_match = PEER_NOW_VOTE_RE.search(line)
            if peer_now_match and peer_now_match.group(3) == target_tx:
                overlay = peer_now_match.group(1)
                node_data[node]["peer_vote_updates"].append(
                    {
                        "working_seq": target_seq,
                        "timestamp": ts,
                        "time_ms": ts_ms,
                        "peer_overlay_id": overlay,
                        "peer_node": _overlay_node(overlay_map, overlay),
                        "vote": peer_now_match.group(2).lower(),
                        "source": f"{path.name}:{line_no}",
                    }
                )
                continue

            no_change_match = NO_CHANGE_RE.search(line)
            if no_change_match and no_change_match.group(2) == target_tx:
                vote = no_change_match.group(1).lower()
                pending_update = PendingVoteUpdate(
                    timestamp=ts,
                    timestamp_ms=ts_ms,
                    source_line=line_no,
                    tx=target_tx,
                    action="no_change",
                    old_vote=vote,
                    new_vote=vote,
                    weight=int(no_change_match.group(3)),
                    percent=int(no_change_match.group(4)),
                    rounds_with_vote=int(no_change_match.group(5)),
                )
                continue

            we_now_match = WE_NOW_RE.search(line)
            if we_now_match and we_now_match.group(2) == target_tx:
                new_vote = we_now_match.group(1).lower()
                pending_update = PendingVoteUpdate(
                    timestamp=ts,
                    timestamp_ms=ts_ms,
                    source_line=line_no,
                    tx=target_tx,
                    action="changed",
                    old_vote=None,
                    new_vote=new_vote,
                )
                continue

            if pending_update is not None:
                json_match = JSON_VOTE_RE.search(line)
                if json_match:
                    try:
                        pending_update.json_state = json.loads(json_match.group(1))
                    except json.JSONDecodeError:
                        pass
                    continue

                if TIMER_RE.search(line) and "updateOurPositions." in line:
                    converge_match = CONVERGE_RE.search(line)
                    needed_matches = NEEDED_WEIGHT_RE.findall(line)
                    consensus_match = CHECK_CONSENSUS_RE.search(line)
                    required_pct = None
                    for a, b in needed_matches:
                        if a or b:
                            required_pct = int(a or b)
                            break
                    percent_time = (
                        pending_update.percent
                        if pending_update.percent is not None
                        else (None if converge_match is None else int(converge_match.group(1)))
                    )
                    yays = int((pending_update.json_state or {}).get("yays", 0))
                    nays = int((pending_update.json_state or {}).get("nays", 0))
                    our_vote = bool((pending_update.json_state or {}).get("our_vote", False))
                    weight = pending_update.weight
                    if weight is None and (yays or nays):
                        # The JSON is printed after ourVote_ changes.  For a changed vote,
                        # recover the old vote because that is the vote used by updateVote().
                        old_vote_bool = not our_vote if pending_update.action == "changed" else our_vote
                        weight = _compute_weight(yays, nays, old_vote_bool)
                        pending_update.old_vote = "yes" if old_vote_bool else "no"
                    elif pending_update.old_vote is None:
                        pending_update.old_vote = pending_update.new_vote

                    state_before = str(dispute_state["avalanche_state"])
                    counter_before = int(dispute_state["avalanche_counter"])
                    counter_used = counter_before + 1
                    dispute_required_pct, new_state = _dispute_required_pct(
                        state_before, percent_time, counter_used
                    )
                    if new_state is None:
                        dispute_state["avalanche_counter"] = counter_used
                    else:
                        dispute_state["avalanche_state"] = new_state
                        dispute_state["avalanche_counter"] = 0
                    if pending_update.action == "no_change":
                        dispute_state["current_vote_counter"] = (
                            int(dispute_state["current_vote_counter"]) + 1
                        )
                    else:
                        dispute_state["current_vote_counter"] = 0

                    active = _nearest_round(active_rounds, pending_update.timestamp_ms, target_seq)
                    establish = node_data[node]["establish"][-1] if node_data[node]["establish"] else None
                    tick_relative = (
                        None
                        if establish is None
                        else pending_update.timestamp_ms - int(establish["time_ms"])
                    )
                    update_row = {
                        "working_seq": target_seq,
                        "timestamp": pending_update.timestamp,
                        "time_ms": pending_update.timestamp_ms,
                        "relative_to_establish_ms": tick_relative,
                        "relative_to_round_start_ms": None
                        if active is None
                        else pending_update.timestamp_ms - active.start_ms,
                        "tx": target_tx,
                        "action": pending_update.action,
                        "old_vote": pending_update.old_vote,
                        "new_vote": pending_update.new_vote,
                        "yays": yays,
                        "nays": nays,
                        "our_vote_after": (pending_update.json_state or {}).get("our_vote"),
                        "weight": weight,
                        "percent": percent_time,
                        "round_time_ms": None if converge_match is None else int(converge_match.group(2)),
                        "prev_round_time_ms": None if converge_match is None else int(converge_match.group(3)),
                        "av_min_consensus_time_ms": None
                        if converge_match is None
                        else int(converge_match.group(4)),
                        "required_pct": dispute_required_pct,
                        "avalanche_state_before": state_before,
                        "avalanche_state_after": dispute_state["avalanche_state"],
                        "avalanche_counter_before": counter_before,
                        "avalanche_counter_used": counter_used,
                        "avalanche_counter_after": dispute_state["avalanche_counter"],
                        "current_vote_counter_after": dispute_state["current_vote_counter"],
                        "close_time_needed_weight": required_pct,
                        "check_consensus": None
                        if consensus_match is None
                        else {
                            "proposing": int(consensus_match.group(1)),
                            "total": int(consensus_match.group(2)),
                            "agree": int(consensus_match.group(3)),
                            "validated": int(consensus_match.group(4)),
                            "time_ms": int(consensus_match.group(5)),
                            "previous_time_ms": int(consensus_match.group(6)),
                        },
                        "votes": (pending_update.json_state or {}).get("votes", {}),
                        "source": f"{path.name}:{pending_update.source_line}",
                    }
                    node_data[node]["vote_updates"].append(update_row)
                    pending_update = None
                    continue

            position_match = POSITION_CHANGE_RE.search(line)
            if position_match:
                active = _nearest_round(active_rounds, ts_ms, target_seq)
                if active is not None:
                    node_data[node]["position_changes"].append(
                        {
                            "working_seq": target_seq,
                            "timestamp": ts,
                            "time_ms": ts_ms,
                            "close_time": int(position_match.group(1)),
                            "txset": position_match.group(2),
                            "source": f"{path.name}:{line_no}",
                        }
                    )

            build_match = BUILDING_SET_RE.search(line)
            if build_match:
                active = _nearest_round(active_rounds, ts_ms, target_seq)
                if active is not None:
                    node_data[node].setdefault("_pending_build_set", build_match.group(1))

            built_match = BUILT_LEDGER_RE.search(line)
            if built_match and int(built_match.group(1)) == target_seq:
                node_data[node]["built_ledgers"].append(
                    {
                        "working_seq": target_seq,
                        "timestamp": ts,
                        "time_ms": ts_ms,
                        "txset": node_data[node].pop("_pending_build_set", ""),
                        "ledger": built_match.group(2),
                        "source": f"{path.name}:{line_no}",
                    }
                )

    for data in node_data.values():
        data.pop("_pending_build_set", None)
    return {"nodes": node_data}


def _proposal_summary(event_rows: list[dict[str, Any]], target_seq: int) -> dict[str, Any]:
    origin: dict[int, list[dict[str, Any]]] = defaultdict(list)
    receives: list[dict[str, Any]] = []
    for row in event_rows:
        try:
            working_seq = int(row.get("working_seq"))
        except (TypeError, ValueError):
            continue
        if working_seq != target_seq:
            continue
        event_type = row.get("event_type")
        if event_type == "proposal_origin_send":
            try:
                node = int(row["node"])
            except (TypeError, ValueError):
                continue
            origin[node].append(row)
        elif event_type == "proposal_receive":
            receives.append(row)

    initial: dict[int, dict[str, Any]] = {}
    updates: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for node, rows in origin.items():
        rows = sorted(rows, key=lambda r: (str(r.get("sort_key")), str(r.get("proposal_seq"))))
        for row in rows:
            proposal_seq = row.get("proposal_seq")
            item = {
                "timestamp": row.get("timestamp"),
                "time_ms": _timestamp_ms(str(row.get("timestamp"))),
                "proposal_seq": proposal_seq,
                "txset": row.get("position_hash"),
                "close_time": row.get("close_time"),
                "source": f"{row.get('source_file')}:{row.get('source_line')}",
            }
            if str(proposal_seq) == "0" and node not in initial:
                initial[node] = item
            else:
                updates[node].append(item)

    deliveries = []
    for row in sorted(receives, key=lambda r: str(r.get("sort_key"))):
        deliveries.append(
            {
                "timestamp": row.get("timestamp"),
                "time_ms": _timestamp_ms(str(row.get("timestamp"))),
                "sender": row.get("sender_node"),
                "receiver": row.get("receiver_node"),
                "proposal_seq": row.get("proposal_seq"),
                "txset": row.get("position_hash"),
                "close_time": row.get("close_time"),
                "source": f"{row.get('source_file')}:{row.get('source_line')}",
            }
        )
    return {"initial": initial, "updates": dict(updates), "deliveries": deliveries}


def _accepted_split(nodes: dict[int, dict[str, Any]]) -> dict[str, list[int]]:
    split: dict[str, list[int]] = defaultdict(list)
    for node, data in nodes.items():
        built = data.get("built_ledgers") or []
        if not built:
            continue
        txset = built[0].get("txset") or ""
        split[txset].append(int(node))
    return {txset: sorted(members) for txset, members in sorted(split.items())}


def _build_replay_hints(
    proposals: dict[str, Any],
    nodes: dict[int, dict[str, Any]],
    target_tx: str,
) -> dict[str, Any]:
    node_timing: dict[int, dict[str, Any]] = {}
    ticks_by_node: dict[int, list[dict[str, Any]]] = {}
    for node, data in nodes.items():
        rounds = data.get("rounds") or []
        establish = data.get("establish") or []
        vote_updates = data.get("vote_updates") or []
        first_round = rounds[0] if rounds else {}
        first_establish = establish[0] if establish else {}
        ticks = []
        for idx, update in enumerate(vote_updates, start=1):
            tick = {
                "tick_index": idx,
                "timestamp": update.get("timestamp"),
                "time_ms": update.get("time_ms"),
                "relative_to_round_start_ms": update.get(
                    "relative_to_round_start_ms"
                ),
                "relative_to_establish_ms": update.get(
                    "relative_to_establish_ms"
                ),
                "round_time_ms": update.get("round_time_ms"),
                "prev_round_time_ms": update.get("prev_round_time_ms"),
                "derived_required_pct": update.get("required_pct"),
                "weight": update.get("weight"),
                "old_vote": update.get("old_vote"),
                "new_vote": update.get("new_vote"),
            }
            ticks.append(tick)
        ticks_by_node[node] = ticks
        node_timing[node] = {
            "round_start_timestamp": first_round.get("start_timestamp"),
            "round_start_ms": first_round.get("start_ms"),
            "establish_timestamp": first_establish.get("timestamp"),
            "establish_ms": first_establish.get("time_ms"),
            "establish_after_round_start_ms": first_establish.get(
                "relative_to_round_start_ms"
            ),
            "prev_round_time_ms": (
                ticks[0].get("prev_round_time_ms")
                if ticks
                else first_establish.get("prev_round_time_ms")
            ),
            "ticks": ticks,
        }

    delivery_constraints = []
    for delivery in proposals.get("deliveries", []):
        receiver = delivery.get("receiver")
        if receiver in ("", None):
            continue
        try:
            receiver_node = int(receiver)
        except (TypeError, ValueError):
            continue
        delivery_time = delivery.get("time_ms")
        if delivery_time is None:
            continue
        for tick in ticks_by_node.get(receiver_node, []):
            tick_time = tick.get("time_ms")
            if tick_time is None:
                continue
            delivery_constraints.append(
                {
                    "proposal": {
                        "sender": delivery.get("sender"),
                        "receiver": receiver_node,
                        "proposal_seq": delivery.get("proposal_seq"),
                        "txset": delivery.get("txset"),
                        "delivery_timestamp": delivery.get("timestamp"),
                        "delivery_time_ms": delivery_time,
                        "source": delivery.get("source"),
                    },
                    "tick": {
                        "receiver": receiver_node,
                        "tick_index": tick.get("tick_index"),
                        "timestamp": tick.get("timestamp"),
                        "time_ms": tick_time,
                    },
                    "relation": "deliverBefore"
                    if delivery_time <= tick_time
                    else "deliverAfter",
                }
            )

    initial_by_node = {
        int(node): row for node, row in proposals.get("initial", {}).items()
    }
    return {
        "inputs_to_control": [
            "prevRoundTime per node",
            "roundStartTime per node",
            "establishStartTime per node",
            "manual tick time per node",
            "initial local vote/txset per node",
            "proposal delivery before/after each receiver tick",
        ],
        "target_tx": target_tx,
        "initial_txset_by_node": initial_by_node,
        "node_timing": node_timing,
        "delivery_tick_constraints": delivery_constraints,
    }


def build_bug5_trace(
    case_dir: Path,
    *,
    target_seq: int = 9,
    target_tx: str,
) -> dict[str, Any]:
    # Reuse the existing proposal/action decoder for proposal identities and
    # delivery observations.  This import is intentionally lazy so plot/debug
    # commands do not require protobuf.
    from evo.analysis.proposal_trace import analyze_proposal_trace

    proposal_trace = analyze_proposal_trace(case_dir, seqs=[target_seq])
    overlay_map = proposal_trace.get("overlay_identity_map", {})
    logs = _select_logs(case_dir)
    consensus = _scan_consensus_logs(
        logs,
        target_seq=target_seq,
        target_tx=target_tx,
        overlay_map=overlay_map,
    )
    nodes = consensus["nodes"]
    proposals = _proposal_summary(proposal_trace["event_rows"], target_seq)
    initial_counts = Counter(
        item.get("txset", "") for item in proposals["initial"].values() if item.get("txset")
    )
    accepted_split = _accepted_split(nodes)

    return {
        "schema": "rocket.csf_consensus_trace.v1",
        "case_dir": str(case_dir.expanduser().resolve()),
        "target_seq": target_seq,
        "target_tx": target_tx,
        "short_names": {
            "target_tx": _short(target_tx),
            **{
                f"txset_{idx}": _short(txset)
                for idx, txset in enumerate(sorted(initial_counts), start=1)
            },
        },
        "proposal_trace_notes": proposal_trace.get("notes", []),
        "initial_proposals": proposals["initial"],
        "initial_proposal_counts": dict(initial_counts),
        "proposal_updates": proposals["updates"],
        "proposal_deliveries": proposals["deliveries"],
        "consensus": consensus,
        "accepted_split_by_txset": accepted_split,
        "replay_hints": _build_replay_hints(proposals, nodes, target_tx),
    }


def run_bug5_trace(
    case_dir: Path,
    *,
    target_seq: int = 9,
    target_tx: str,
    out_dir: Path | None = None,
) -> list[Path]:
    case_dir = case_dir.expanduser().resolve()
    target_dir = analysis_dir(case_dir) if out_dir is None else out_dir.expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    trace = build_bug5_trace(case_dir, target_seq=target_seq, target_tx=target_tx)
    out_path = target_dir / "bug5_consensus_trace.json"
    out_path.write_text(json.dumps(trace, indent=2, sort_keys=True), encoding="utf-8")
    return [out_path]


def _bool_literal(value: bool) -> str:
    return "true" if value else "false"


def _array_rows(type_name: str, rows: list[str]) -> str:
    if not rows:
        return ""
    return "\n".join(rows)


def render_csf_fixture(
    trace: dict[str, Any],
    *,
    has_target_txset: str,
    source_name: str = "bug5_consensus_trace.json",
) -> str:
    """Render a C++ CSF replay fixture from a bug5-style consensus trace.

    The replay fixture intentionally models a single disputed transaction as a
    binary txset choice: the concrete txset hash supplied by `has_target_txset`
    maps to "contains target tx"; every other txset must be the same opposite
    side.  This keeps the simulator witness honest instead of silently
    flattening traces with multiple independent transaction differences.
    """

    initial = {
        int(node): row for node, row in (trace.get("initial_proposals") or {}).items()
    }
    consensus_nodes = {
        int(node): row for node, row in (trace.get("consensus", {}).get("nodes") or {}).items()
    }
    accepted_split = trace.get("accepted_split_by_txset") or {}
    deliveries = trace.get("proposal_deliveries") or []

    txsets: set[str] = set()
    txsets.update(row.get("txset", "") for row in initial.values())
    txsets.update(txset for txset in accepted_split)
    txsets.update(row.get("txset", "") for row in deliveries)
    txsets.discard("")
    if has_target_txset not in txsets:
        raise ValueError(f"--has-target-txset is not present in the trace: {has_target_txset}")
    opposite_txsets = sorted(txset for txset in txsets if txset != has_target_txset)
    if len(opposite_txsets) > 1:
        raise ValueError(
            "CSF fixture supports one target txset plus one opposite txset; "
            f"found opposite txsets: {opposite_txsets}"
        )

    timestamps: list[str] = []
    for node_data in consensus_nodes.values():
        for round_info in node_data.get("rounds") or []:
            if round_info.get("start_timestamp"):
                timestamps.append(str(round_info["start_timestamp"]))
        for establish in node_data.get("establish") or []:
            if establish.get("timestamp"):
                timestamps.append(str(establish["timestamp"]))
        for update in node_data.get("vote_updates") or []:
            if update.get("timestamp"):
                timestamps.append(str(update["timestamp"]))
        for built in node_data.get("built_ledgers") or []:
            if built.get("timestamp"):
                timestamps.append(str(built["timestamp"]))
    for delivery in deliveries:
        if delivery.get("timestamp"):
            timestamps.append(str(delivery["timestamp"]))
    if not timestamps:
        raise ValueError("Trace has no timestamps to anchor the replay fixture")
    base_us = min(_timestamp_us(ts) for ts in timestamps)

    def rel_us(timestamp: str) -> int:
        return _timestamp_us(timestamp) - base_us

    def txset_has_target(txset: str) -> bool:
        if txset == has_target_txset:
            return True
        if txset in opposite_txsets:
            return False
        raise ValueError(f"Unexpected txset in trace: {txset}")

    accepted_by_node: dict[int, bool] = {}
    for txset, nodes in accepted_split.items():
        for node in nodes:
            accepted_by_node[int(node)] = txset_has_target(txset)

    node_rows: list[str] = []
    for node in sorted(initial):
        node_data = consensus_nodes.get(node, {})
        rounds = node_data.get("rounds") or []
        establish = node_data.get("establish") or []
        if not rounds:
            raise ValueError(f"Node {node} has no target round in trace")
        if not establish:
            raise ValueError(f"Node {node} has no establish transition in trace")
        if node not in accepted_by_node:
            raise ValueError(f"Node {node} has no accepted txset in trace")
        round_info = rounds[0]
        establish_info = establish[0]
        prev_round_ms = establish_info.get("prev_round_time_ms")
        if prev_round_ms is None:
            prev_round_ms = (
                trace.get("replay_hints", {})
                .get("node_timing", {})
                .get(str(node), {})
                .get("prev_round_time_ms")
            )
        if prev_round_ms is None:
            raise ValueError(f"Node {node} has no prevRoundTime in trace")
        prev_proposers = round_info.get("previous_proposers")
        if prev_proposers is None:
            raise ValueError(f"Node {node} has no previous_proposers in trace")
        node_rows.append(
            "    NodeTiming{"
            f"{node}, "
            f"{rel_us(str(round_info['start_timestamp']))}, "
            f"{rel_us(str(establish_info['timestamp']))}, "
            f"{int(prev_round_ms)}, "
            f"{int(prev_proposers)}, "
            f"{_bool_literal(txset_has_target(str(initial[node]['txset'])))}, "
            f"{_bool_literal(accepted_by_node[node])}"
            "},"
        )

    delivery_rows: list[str] = []
    expected_proposals: set[tuple[int, int, bool]] = set()
    for node, row in initial.items():
        expected_proposals.add(
            (
                node,
                int(row["proposal_seq"]),
                txset_has_target(str(row["txset"])),
            )
        )
    for node_text, rows in (trace.get("proposal_updates") or {}).items():
        node = int(node_text)
        for row in rows:
            expected_proposals.add(
                (
                    node,
                    int(row["proposal_seq"]),
                    txset_has_target(str(row["txset"])),
                )
            )
    for delivery in sorted(deliveries, key=lambda row: _timestamp_us(str(row["timestamp"]))):
        proposal_seq = int(delivery["proposal_seq"])
        expected_proposals.add(
            (
                int(delivery["sender"]),
                proposal_seq,
                txset_has_target(str(delivery["txset"])),
            )
        )
        delivery_rows.append(
            "    ProposalDelivery{"
            f"{rel_us(str(delivery['timestamp']))}, "
            f"{int(delivery['sender'])}, "
            f"{int(delivery['receiver'])}, "
            f"{proposal_seq}, "
            f"{_bool_literal(txset_has_target(str(delivery['txset'])))}"
            "},"
        )

    tick_events: list[tuple[int, int, int]] = []
    for node, node_data in sorted(consensus_nodes.items()):
        for update in node_data.get("vote_updates") or []:
            if update.get("timestamp"):
                check_consensus = update.get("check_consensus") or {}
                tick_events.append(
                    (
                        rel_us(str(update["timestamp"])),
                        node,
                        int(check_consensus.get("validated") or 0),
                    )
                )
    tick_rows = [
        f"    TimerTick{{{at_us}, {node}, {validated}}},"
        for at_us, node, validated in sorted(tick_events)
    ]

    accept_events: list[tuple[int, int]] = []
    for node, node_data in sorted(consensus_nodes.items()):
        built = node_data.get("built_ledgers") or []
        if not built:
            continue
        accept_events.append((rel_us(str(built[0]["timestamp"])), node))
    accept_rows = [
        f"    TimerTick{{{at_us}, {node}, 0}}," for at_us, node in sorted(accept_events)
    ]

    expected_proposal_rows = [
        "    ExpectedProposal{"
        f"{sender}, {seq}, {_bool_literal(has_target)}"
        "},"
        for sender, seq, has_target in sorted(expected_proposals)
    ]

    target_seq = trace.get("target_seq")
    target_tx = trace.get("target_tx")
    case_name = Path(str(trace.get("case_dir", ""))).name or "unknown"
    opposite_comment = opposite_txsets[0] if opposite_txsets else "<none>"

    return "\n".join(
        [
            f"// GENERATED from {source_name}; do not edit by hand without regenerating.",
            f"// Source case: {case_name}, target seq {target_seq}, target tx {target_tx}",
            f"// Target txset: {has_target_txset}; opposite txset: {opposite_comment}",
            "#ifndef RIPPLE_TEST_CONSENSUS_BUG5_TRACE_FIXTURE_H_INCLUDED",
            "#define RIPPLE_TEST_CONSENSUS_BUG5_TRACE_FIXTURE_H_INCLUDED",
            "",
            "#include <array>",
            "#include <cstdint>",
            "",
            "namespace ripple {",
            "namespace test {",
            "namespace bug5_trace {",
            "",
            "struct NodeTiming",
            "{",
            "    std::uint32_t node;",
            "    std::int64_t roundStartUs;",
            "    std::int64_t establishUs;",
            "    std::uint32_t prevRoundTimeMs;",
            "    std::uint32_t prevProposers;",
            "    bool initialHasTarget;",
            "    bool expectedHasTarget;",
            "};",
            "",
            "struct ProposalDelivery",
            "{",
            "    std::int64_t atUs;",
            "    std::uint32_t sender;",
            "    std::uint32_t receiver;",
            "    std::uint32_t proposalSeq;",
            "    bool hasTarget;",
            "};",
            "",
            "struct ExpectedProposal",
            "{",
            "    std::uint32_t sender;",
            "    std::uint32_t proposalSeq;",
            "    bool hasTarget;",
            "};",
            "",
            "struct TimerTick",
            "{",
            "    std::int64_t atUs;",
            "    std::uint32_t node;",
            "    std::uint32_t observedValidated;",
            "};",
            "",
            f"inline constexpr std::int64_t sourceBaseUnixUs = {base_us};",
            "",
            f"inline constexpr std::array<NodeTiming, {len(node_rows)}> nodes{{{{",
            _array_rows("NodeTiming", node_rows),
            "}};",
            "",
            f"inline constexpr std::array<ProposalDelivery, {len(delivery_rows)}> deliveries{{{{",
            _array_rows("ProposalDelivery", delivery_rows),
            "}};",
            "",
            f"inline constexpr std::array<ExpectedProposal, {len(expected_proposal_rows)}> expectedProposals{{{{",
            _array_rows("ExpectedProposal", expected_proposal_rows),
            "}};",
            "",
            f"inline constexpr std::array<TimerTick, {len(tick_rows)}> ticks{{{{",
            _array_rows("TimerTick", tick_rows),
            "}};",
            "",
            f"inline constexpr std::array<TimerTick, {len(accept_rows)}> acceptTicks{{{{",
            _array_rows("TimerTick", accept_rows),
            "}};",
            "",
            "}  // namespace bug5_trace",
            "}  // namespace test",
            "}  // namespace ripple",
            "",
            "#endif",
            "",
        ]
    )


def write_csf_fixture(
    trace_path: Path,
    *,
    has_target_txset: str,
    out_path: Path,
) -> Path:
    trace_path = trace_path.expanduser().resolve()
    out_path = out_path.expanduser().resolve()
    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    rendered = render_csf_fixture(
        trace,
        has_target_txset=has_target_txset,
        source_name=trace_path.name,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    return out_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Extract a consensus-level bug5 trace")
    parser.add_argument("case_dir")
    parser.add_argument("--seq", type=int, default=9)
    parser.add_argument("--tx", required=True, help="Disputed transaction hash")
    parser.add_argument("--out-dir", default=None)
    args = parser.parse_args(argv)
    for path in run_bug5_trace(
        Path(args.case_dir),
        target_seq=args.seq,
        target_tx=args.tx,
        out_dir=None if args.out_dir is None else Path(args.out_dir),
    ):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
