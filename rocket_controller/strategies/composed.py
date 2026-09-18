import random
import threading
import time
from typing import Dict, Tuple

from loguru import logger
from google.protobuf.message import Message
from protos import packet_pb2, ripple_pb2

from rocket_controller.strategies.evo_delay import EvoDelayStrategy
from rocket_controller.strategies.utils import pubkey_to_node_id


SPARSE_SET_RULES = "sparse_set_rules"
SPARSE_SEQ_PROPOSAL_RULES = "sparse_seq_proposal_rules"
SPARSE_SEQ_PROPOSAL_SET_RULES = "sparse_seq_proposal_set_rules"
OPEN_LATE_PART_GROUPS = "open_late_part_groups"
OPEN_PROPOSAL_SEQ = -1


class ComposedStrategy(EvoDelayStrategy):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.delay_cfg = self.encoding["DelayEncoding"]
        self.partition_cfg = self.encoding["PartitionEncoding"]
        self.byzz_cfg = self.encoding["ByzzEncoding"]

        self.delay_mode = self.delay_cfg["mode"]
        self.partition_mode = self.partition_cfg["mode"]
        self.byzz_mode = self.byzz_cfg["mode"]

        self.delay_min = self.params.get("min_delay_ms", 0)
        self.delay_max = self.params.get("max_delay_ms", 100)

        self.partition_seq = self.partition_cfg.get("partition_seq")
        self.partition_duration = self.partition_cfg.get("partition_duration", 0)
        self.start_partition = self.partition_cfg.get("start_partition", "open")
        if self.start_partition not in ["open", "establish"]:
            raise ValueError(f"Unsupported start_partition: {self.start_partition}")
        self.partition_lock = threading.Lock()
        self.partition_start_time = None
        self.partition_started_once = False
        self.partition = None
        self.partition_runtime_rules = []
        self.partition_node_states: Dict[int, Tuple[int, int]] = {}

        self.delay_rule_table: Dict[Tuple[int, int, str], int] = {}
        self.delay_rule_table_by_seq: Dict[Tuple[int, int, int, str], int] = {}
        self.delay_rule_table_by_seq_proposal: Dict[
            Tuple[int, int, int, int, str],
            int,
        ] = {}
        self.delay_set_rules = []
        self.byzz_rule_table: Dict[Tuple[int, int, str], str] = {}
        self.byzz_rule_table_by_seq_proposal: Dict[
            Tuple[int, int, int, str],
            str,
        ] = {}
        self.byzz_set_rules = []
        self.latest_proposal_seq_by_node: Dict[Tuple[int, int], int] = {}

        # logger.error(
        #     f"ComposedStrategy initialized with delay_mode={self.delay_mode}, "
        #     f"partition_mode={self.partition_mode}, byzz_mode={self.byzz_mode}"
        # )

    def _sample_partition_shuffle_cut(self, num_nodes: int) -> list[int]:
        nodes = list(range(num_nodes))
        random.shuffle(nodes)
        cut = random.randint(1, num_nodes - 1)

        partition = [0] * num_nodes
        for i, idx in enumerate(nodes):
            if i < cut:
                partition[idx] = 0
            else:
                partition[idx] = 1
        return partition

    def _partition_rule_configs(self):
        if self.partition_cfg.get("partition_rules"):
            return list(self.partition_cfg["partition_rules"])
        if self.partition_mode in [
            "bi_part_groups",
            "flex_bi_part_groups",
            "flex_msg_part_groups",
            OPEN_LATE_PART_GROUPS,
        ]:
            partition = self.partition_cfg.get("partition")
            if partition is None:
                return []
            return [
                {
                    "partition_seq": self.partition_cfg.get("partition_seq"),
                    "partition_duration": self.partition_cfg.get("partition_duration", 0),
                    "partition": partition,
                }
            ]
        if self.partition_mode == "random_bipart":
            return [
                {
                    "partition_seq": self.partition_cfg.get("partition_seq"),
                    "partition_duration": self.partition_cfg.get("partition_duration", 0),
                    "partition": None,
                }
            ]
        return []

    def _normalize_partition_rule(self, rule):
        partition = rule.get("partition")
        normalized_partition = None
        if partition is not None:
            normalized_partition = [int(value) for value in partition]
            if len(normalized_partition) != self.network.node_amount:
                raise ValueError(
                    f"partition length {len(normalized_partition)} != node amount "
                    f"{self.network.node_amount}"
                )
            if any(value not in (0, 1) for value in normalized_partition):
                raise ValueError("partition values must be 0 or 1")
            if len(set(normalized_partition)) < 2:
                raise ValueError("partition rules require at least two groups")
        message_type = rule.get("message_type")
        if self.partition_mode == "flex_msg_part_groups" and not message_type:
            raise ValueError("flex_msg_part_groups partition rules require message_type")
        return {
            "partition_seq": int(rule["partition_seq"]),
            "partition_duration": int(
                rule.get(
                    "partition_duration",
                    self.partition_cfg.get("partition_duration", 0),
                )
            ),
            "partition": normalized_partition,
            "active_partition": None,
            "start_partition": str(rule.get("start_partition", self.start_partition)),
            "start_after_ms": int(rule.get("start_after_ms", 0)),
            "message_type": str(message_type) if message_type else None,
            "anchor_time": None,
            "start_time": None,
            "started_once": False,
        }

    def _sync_legacy_partition_state(self):
        active_rule = next(
            (
                rule
                for rule in self.partition_runtime_rules
                if rule["start_time"] is not None
            ),
            None,
        )
        if active_rule is not None:
            self.partition_seq = active_rule["partition_seq"]
            self.partition_duration = active_rule["partition_duration"]
            self.partition_start_time = active_rule["start_time"]
            self.partition_started_once = bool(active_rule["started_once"])
            self.partition = (
                list(active_rule["active_partition"])
                if active_rule["active_partition"] is not None
                else None
            )
            return

        self.partition_start_time = None
        self.partition_started_once = any(
            rule["started_once"] for rule in self.partition_runtime_rules
        )
        if self.partition_runtime_rules:
            first_rule = self.partition_runtime_rules[0]
            self.partition_seq = first_rule["partition_seq"]
            self.partition_duration = first_rule["partition_duration"]
            if first_rule["partition"] is not None:
                self.partition = list(first_rule["partition"])
            else:
                self.partition = None
        else:
            self.partition = None

    def _get_rule_partition(self, rule):
        if rule["active_partition"] is not None:
            return rule["active_partition"]
        return rule["partition"]

    def setup(self):
        self.delay_rule_table.clear()
        self.delay_rule_table_by_seq.clear()
        self.delay_rule_table_by_seq_proposal.clear()
        self.delay_set_rules.clear()
        self.byzz_rule_table.clear()
        self.byzz_rule_table_by_seq_proposal.clear()
        self.byzz_set_rules.clear()
        self.latest_proposal_seq_by_node.clear()
        self.partition_start_time = None
        self.partition_started_once = False
        self.partition = None
        self.partition_runtime_rules.clear()
        self.partition_node_states.clear()

        self.partition_runtime_rules = [
            self._normalize_partition_rule(rule)
            for rule in self._partition_rule_configs()
        ]
        self._sync_legacy_partition_state()

        for rule in self.delay_cfg.get("delays", []):
            if self.delay_mode == "dense_rules":
                key = (
                    int(rule["from_node"]),
                    int(rule["to_node"]),
                    str(rule["message_type"]),
                )
                self.delay_rule_table[key] = int(rule["delay"])
            elif self.delay_mode in ["dense_seq_rules", "sparse_rules"]:
                key = (
                    int(rule["seq"]),
                    int(rule["from_node"]),
                    int(rule["to_node"]),
                    str(rule["message_type"]),
                )
                self.delay_rule_table_by_seq[key] = int(rule["delay"])
            elif self.delay_mode == SPARSE_SEQ_PROPOSAL_RULES:
                key = (
                    int(rule["seq"]),
                    int(rule["pro_seq"]),
                    int(rule["from_node"]),
                    int(rule["to_node"]),
                    str(rule["message_type"]),
                )
                self.delay_rule_table_by_seq_proposal[key] = int(rule["delay"])
            elif self.delay_mode == SPARSE_SET_RULES:
                self.delay_set_rules.append(
                    {
                        "seq": int(rule["seq"]),
                        "pro_seq": None,
                        "from_nodes": frozenset(int(n) for n in rule["from_nodes"]),
                        "to_nodes": frozenset(int(n) for n in rule["to_nodes"]),
                        "message_type": str(rule["message_type"]),
                        "delay": int(rule["delay"]),
                    }
                )
            elif self.delay_mode == SPARSE_SEQ_PROPOSAL_SET_RULES:
                self.delay_set_rules.append(
                    {
                        "seq": int(rule["seq"]),
                        "pro_seq": int(rule["pro_seq"]),
                        "from_nodes": frozenset(int(n) for n in rule["from_nodes"]),
                        "to_nodes": frozenset(int(n) for n in rule["to_nodes"]),
                        "message_type": str(rule["message_type"]),
                        "delay": int(rule["delay"]),
                    }
                )

        for rule in self.byzz_cfg.get("byzz_rules", []):
            if self.byzz_mode == SPARSE_SEQ_PROPOSAL_RULES:
                key = (
                    int(rule["seq"]),
                    int(rule["pro_seq"]),
                    int(rule["to_node"]),
                    str(rule["message_type"]),
                )
                self.byzz_rule_table_by_seq_proposal[key] = str(
                    rule["mutation_method"]
                )
            elif self.byzz_mode == SPARSE_SET_RULES:
                self.byzz_set_rules.append(
                    {
                        "seq": int(rule["seq"]),
                        "pro_seq": None,
                        "to_nodes": frozenset(int(n) for n in rule["to_nodes"]),
                        "message_type": str(rule["message_type"]),
                        "mutation_method": str(rule["mutation_method"]),
                    }
                )
            elif self.byzz_mode == SPARSE_SEQ_PROPOSAL_SET_RULES:
                self.byzz_set_rules.append(
                    {
                        "seq": int(rule["seq"]),
                        "pro_seq": int(rule["pro_seq"]),
                        "to_nodes": frozenset(int(n) for n in rule["to_nodes"]),
                        "message_type": str(rule["message_type"]),
                        "mutation_method": str(rule["mutation_method"]),
                    }
                )
            else:
                key = (
                    int(rule["seq"]),
                    int(rule["to_node"]),
                    str(rule["message_type"]),
                )
                self.byzz_rule_table[key] = str(rule["mutation_method"])

        # if self.partition_mode == "random_bipart":
        #     logger.error(
        #         "Partition setup: random_bipart mode, layout will be generated at activation"
        #     )
        # if self.partition_mode != "none":
        #     logger.error(f"Partition setup: {self.partition}")

    def observe_packet_for_strategy_state(
        self,
        message: Message,
        packet: packet_pb2.Packet,
        current_ledger: int,
    ) -> None:
        sender_node_id = self.network.port_to_id(packet.from_port)
        if isinstance(message, ripple_pb2.TMStatusChange):
            key = (sender_node_id, int(message.ledgerSeq))
            self.latest_proposal_seq_by_node.setdefault(key, OPEN_PROPOSAL_SEQ)

        if self.partition_mode == "none":
            return
        if not any(
            rule["start_partition"] == "establish"
            for rule in self.partition_runtime_rules
        ):
            return
        if not isinstance(message, ripple_pb2.TMStatusChange):
            return

        with self.partition_lock:
            self.partition_node_states[sender_node_id] = (
                int(message.ledgerSeq),
                int(message.newEvent),
            )

    def get_proposal_sequence_for_packet(
        self,
        message: Message,
        packet: packet_pb2.Packet,
        current_ledger: int,
    ) -> int:
        sender_node_id = self.network.port_to_id(packet.from_port)
        if isinstance(message, ripple_pb2.TMProposeSet):
            proposer_node_id = pubkey_to_node_id(self, message.nodePubKey.hex())
            if proposer_node_id is None:
                proposer_node_id = sender_node_id
            pro_seq = int(message.proposeSeq)
            self.latest_proposal_seq_by_node[
                (proposer_node_id, current_ledger)
            ] = pro_seq
            return pro_seq
        return self.latest_proposal_seq_by_node.get(
            (sender_node_id, current_ledger),
            OPEN_PROPOSAL_SEQ,
        )

    def _get_set_rule_delay(
        self,
        current_ledger: int,
        pro_seq: int,
        sender_node_id: int,
        receiver_node_id: int,
        msg_name: str,
    ) -> int:
        matches = [
            rule
            for rule in self.delay_set_rules
            if rule["seq"] == current_ledger
            and (rule["pro_seq"] is None or rule["pro_seq"] == pro_seq)
            and rule["message_type"] == msg_name
            and sender_node_id in rule["from_nodes"]
            and receiver_node_id in rule["to_nodes"]
        ]
        if not matches:
            return 0
        best = min(
            matches,
            key=lambda rule: (
                len(rule["from_nodes"]) * len(rule["to_nodes"]),
                -rule["delay"],
                tuple(sorted(rule["from_nodes"])),
                tuple(sorted(rule["to_nodes"])),
            ),
        )
        return best["delay"]

    def _get_set_rule_mutation_method(
        self,
        current_ledger: int,
        pro_seq: int,
        to_node_id: int,
        msg_name: str,
    ) -> str:
        matches = [
            rule
            for rule in self.byzz_set_rules
            if rule["seq"] == current_ledger
            and (rule["pro_seq"] is None or rule["pro_seq"] == pro_seq)
            and rule["message_type"] == msg_name
            and to_node_id in rule["to_nodes"]
        ]
        if not matches:
            return "do_nothing"
        best = min(
            matches,
            key=lambda rule: (
                len(rule["to_nodes"]),
                tuple(sorted(rule["to_nodes"])),
                rule["mutation_method"],
            ),
        )
        return best["mutation_method"]

    def _has_establish_started(self, target_seq: int) -> bool:
        return any(
            ledger_seq == target_seq
            and event == ripple_pb2.neCLOSING_LEDGER
            for ledger_seq, event in self.partition_node_states.values()
        )

    def _should_start_partition(self, rule, current_ledger: int) -> bool:
        if rule["start_partition"] == "open":
            return current_ledger == rule["partition_seq"]
        if rule["start_partition"] == "establish":
            return self._has_establish_started(rule["partition_seq"])
        raise ValueError(f"Unsupported start_partition: {rule['start_partition']}")

    def _maybe_update_partition_state(self, current_ledger: int, cur_time: float) -> None:
        if self.partition_mode == "none":
            return

        for rule in self.partition_runtime_rules:
            if rule["start_time"] is not None:
                if (
                    cur_time - rule["start_time"]
                    >= rule["partition_duration"] / 1000.0
                ):
                    rule["start_time"] = None
                    rule["active_partition"] = None
                continue

            if rule["started_once"]:
                continue

            if rule["anchor_time"] is None:
                if not self._should_start_partition(rule, current_ledger):
                    continue
                rule["anchor_time"] = cur_time

            start_time = rule["anchor_time"] + rule["start_after_ms"] / 1000.0
            end_time = start_time + rule["partition_duration"] / 1000.0
            if cur_time >= end_time:
                rule["started_once"] = True
                rule["anchor_time"] = None
                rule["active_partition"] = None
                continue

            if cur_time >= start_time:
                rule["start_time"] = start_time
                rule["started_once"] = True
                if self.partition_mode == "random_bipart":
                    rule["active_partition"] = self._sample_partition_shuffle_cut(
                        self.network.node_amount
                    )
                else:
                    rule["active_partition"] = list(rule["partition"])

        self._sync_legacy_partition_state()

    def get_delay(
        self,
        message_type,
        packet,
        current_ledger,
        message_cls,
        pro_seq=None,
    ):
        sender_node_id = self.network.port_to_id(packet.from_port)
        receiver_node_id = self.network.port_to_id(packet.to_port)
        msg_name = message_cls.__name__
        pro_seq = OPEN_PROPOSAL_SEQ if pro_seq is None else int(pro_seq)

        if self.delay_mode == "none":
            base_delay = 0
        elif self.delay_mode == "random":
            base_delay = random.randint(self.delay_min, self.delay_max)
        elif self.delay_mode == "dense_rules":
            key = (sender_node_id, receiver_node_id, msg_name)
            base_delay = self.delay_rule_table.get(key, 0)
        elif self.delay_mode in ["dense_seq_rules", "sparse_rules"]:
            key = (current_ledger, sender_node_id, receiver_node_id, msg_name)
            base_delay = self.delay_rule_table_by_seq.get(key, 0)
        elif self.delay_mode == SPARSE_SEQ_PROPOSAL_RULES:
            key = (
                current_ledger,
                pro_seq,
                sender_node_id,
                receiver_node_id,
                msg_name,
            )
            base_delay = self.delay_rule_table_by_seq_proposal.get(key, 0)
        elif self.delay_mode in [SPARSE_SET_RULES, SPARSE_SEQ_PROPOSAL_SET_RULES]:
            base_delay = self._get_set_rule_delay(
                current_ledger,
                pro_seq,
                sender_node_id,
                receiver_node_id,
                msg_name,
            )
        else:
            raise ValueError(f"Unsupported delay mode: {self.delay_mode}")

        cur_time = time.time()
        with self.partition_lock:
            self._maybe_update_partition_state(current_ledger, cur_time)
            partition_delay = self.get_partition_delay(
                cur_time, sender_node_id, receiver_node_id, msg_name
            )
            if partition_delay > 0:
                return partition_delay

        return base_delay

    def are_partitioned(self, sender_node_id, receiver_node_id, msg_name=None):
        if self.partition_mode == "none":
            return False
        for rule in self.partition_runtime_rules:
            if rule["start_time"] is None:
                continue
            rule_msg = rule.get("message_type")
            if rule_msg is not None and rule_msg != msg_name:
                continue
            partition = self._get_rule_partition(rule)
            if partition is None:
                continue
            if partition[sender_node_id] != partition[receiver_node_id]:
                return True
        return False

    def get_partition_delay(
        self,
        cur_time,
        sender_node_id: int | None = None,
        receiver_node_id: int | None = None,
        msg_name: str | None = None,
    ):
        if self.partition_mode == "none":
            return 0

        max_remaining = 0
        for rule in self.partition_runtime_rules:
            start = rule["start_time"]
            if start is None:
                continue
            rule_msg = rule.get("message_type")
            if rule_msg is not None and rule_msg != msg_name:
                continue
            partition = self._get_rule_partition(rule)
            if partition is None:
                continue
            if sender_node_id is not None and receiver_node_id is not None:
                if partition[sender_node_id] == partition[receiver_node_id]:
                    continue
            remaining = int(
                (start * 1000 + rule["partition_duration"]) - (cur_time * 1000)
            )
            if remaining > max_remaining:
                max_remaining = remaining
        return max(0, max_remaining)

    def get_mutation_method(
        self,
        message,
        packet: packet_pb2.Packet | None = None,
        current_ledger: int | None = None,
        pro_seq: int | None = None,
    ) -> str:
        if self.byzz_mode == "none":
            return "do_nothing"
        if self.byzz_mode == "random":
            return self.byzz_mutator.get_mutation_method_50_percent(message)
        if self.byzz_mode in [
            "sparse_rules",
            SPARSE_SET_RULES,
            SPARSE_SEQ_PROPOSAL_RULES,
            SPARSE_SEQ_PROPOSAL_SET_RULES,
        ]:
            assert packet is not None
            assert current_ledger is not None
            to_node_id = self.network.port_to_id(packet.to_port)
            if self.byzz_mode == SPARSE_SEQ_PROPOSAL_RULES:
                pro_seq = OPEN_PROPOSAL_SEQ if pro_seq is None else int(pro_seq)
                key = (current_ledger, pro_seq, to_node_id, type(message).__name__)
                return self.byzz_rule_table_by_seq_proposal.get(key, "do_nothing")
            if self.byzz_mode == SPARSE_SEQ_PROPOSAL_SET_RULES:
                pro_seq = OPEN_PROPOSAL_SEQ if pro_seq is None else int(pro_seq)
                return self._get_set_rule_mutation_method(
                    current_ledger,
                    pro_seq,
                    to_node_id,
                    type(message).__name__,
                )
            if self.byzz_mode == SPARSE_SET_RULES:
                return self._get_set_rule_mutation_method(
                    current_ledger,
                    OPEN_PROPOSAL_SEQ if pro_seq is None else int(pro_seq),
                    to_node_id,
                    type(message).__name__,
                )
            key = (current_ledger, to_node_id, type(message).__name__)
            return self.byzz_rule_table.get(key, "do_nothing")
        raise ValueError(f"Unsupported byzz mode: {self.byzz_mode}")
