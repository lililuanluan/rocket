import random
import threading
import time
from typing import Dict, Tuple

from loguru import logger
from protos import packet_pb2

from rocket_controller.strategies.evo_delay import EvoDelayStrategy


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
        self.partition_lock = threading.Lock()
        self.partition_start_time = None
        self.partition = None

        self.delay_rule_table: Dict[Tuple[int, int, str], int] = {}
        self.delay_rule_table_by_seq: Dict[Tuple[int, int, int, str], int] = {}
        self.byzz_rule_table: Dict[Tuple[int, int, str], str] = {}

        logger.error(
            f"ComposedStrategy initialized with delay_mode={self.delay_mode}, "
            f"partition_mode={self.partition_mode}, byzz_mode={self.byzz_mode}"
        )

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

    def setup(self):
        self.delay_rule_table.clear()
        self.delay_rule_table_by_seq.clear()
        self.byzz_rule_table.clear()
        self.partition_start_time = None

        if self.partition_mode == "random_bipart":
            self.partition = None
        elif self.partition_mode == "bi_part_groups":
            self.partition = self.partition_cfg["partition"]
            if len(self.partition) != self.network.node_amount:
                raise ValueError(
                    f"partition length {len(self.partition)} != node amount "
                    f"{self.network.node_amount}"
                )
        else:
            self.partition = None

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

        for rule in self.byzz_cfg.get("byzz_rules", []):
            key = (
                int(rule["seq"]),
                int(rule["to_node"]),
                str(rule["message_type"]),
            )
            self.byzz_rule_table[key] = str(rule["mutation_method"])

        if self.partition_mode == "random_bipart":
            logger.error(
                "Partition setup: random_bipart mode, layout will be generated at activation"
            )
        if self.partition_mode != "none":
            logger.error(f"Partition setup: {self.partition}")

    def _maybe_update_partition_state(self, current_ledger: int, cur_time: float) -> None:
        if self.partition_mode == "none":
            return

        if self.partition_start_time is not None:
            if cur_time - self.partition_start_time >= self.partition_duration / 1000.0:
                self.partition_start_time = None
                if self.partition_mode == "random_bipart":
                    self.partition = None
            return

        if current_ledger == self.partition_seq:
            self.partition_start_time = cur_time
            if self.partition_mode == "random_bipart":
                self.partition = self._sample_partition_shuffle_cut(
                    self.network.node_amount
                )

    def get_delay(self, message_type, packet, current_ledger, message_cls):
        sender_node_id = self.network.port_to_id(packet.from_port)
        receiver_node_id = self.network.port_to_id(packet.to_port)
        msg_name = message_cls.__name__

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
        else:
            raise ValueError(f"Unsupported delay mode: {self.delay_mode}")

        cur_time = time.time()
        with self.partition_lock:
            self._maybe_update_partition_state(current_ledger, cur_time)
            if self.are_partitioned(sender_node_id, receiver_node_id):
                return self.get_partition_delay(cur_time)

        return base_delay

    def are_partitioned(self, sender_node_id, receiver_node_id):
        if self.partition_mode == "none":
            return False
        if self.partition_mode in ["random_bipart", "bi_part_groups"]:
            partition = self.partition
            if partition is None:
                return False
            return partition[sender_node_id] != partition[receiver_node_id]
        return False

    def get_partition_delay(self, cur_time):
        if self.partition_mode == "none":
            return 0
        start = self.partition_start_time
        if start is None:
            return 0
        remaining = int((start * 1000 + self.partition_duration) - (cur_time * 1000))
        return max(0, remaining)

    def get_mutation_method(
        self,
        message,
        packet: packet_pb2.Packet | None = None,
        current_ledger: int | None = None,
    ) -> str:
        if self.byzz_mode == "none":
            return "do_nothing"
        if self.byzz_mode == "random":
            return self.byzz_mutator.get_mutation_method_50_percent(message)
        if self.byzz_mode == "sparse_rules":
            assert packet is not None
            assert current_ledger is not None
            to_node_id = self.network.port_to_id(packet.to_port)
            key = (current_ledger, to_node_id, type(message).__name__)
            return self.byzz_rule_table.get(key, "do_nothing")
        raise ValueError(f"Unsupported byzz mode: {self.byzz_mode}")
