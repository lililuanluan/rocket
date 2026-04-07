import random
from typing import Any, Dict, Tuple
from functools import singledispatchmethod
import base58

from protos import packet_pb2, ripple_pb2
from rocket_controller.encoder_decoder import (
    DecodingNotSupportedError,
    PacketEncoderDecoder,
    ValidationDict,
)

from rocket_controller.helper import MAX_U32
from rocket_controller.iteration_type import TimeBasedIteration, LedgerBasedIteration
from rocket_controller.strategies.evo_delay import EvoDelayStrategy
from xrpl.core.keypairs.secp256k1 import SECP256K1, sha512_first_half

import serialize
import re
from pathlib import Path
from loguru import logger

import threading
import time


class EvoDelayByzzPartitionStrategy(EvoDelayStrategy):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.partition_lock = threading.Lock()
        self.partition_start_time = None

        self.partition = self.encoding["partition"]
        self.partition_seq = self.encoding["partition_seq"]
        self.partition_duration = self.encoding["partition_duration"]

        # Normalized rule tables for fast lookup.
        # delay key: (seq, from_node, to_node, message_cls_name) -> delay_ms
        self.delay_rule_table: Dict[Tuple[int, int, int, str], int] = {}
        # byzz key: (seq, to_node, message_cls_name) -> mutation_method
        self.byzz_rule_table: Dict[Tuple[int, int, str], str] = {}
        self._load_rules_from_encoding()

        # logger.error(self.delay_rule_table)
        # logger.error(self.byzz_rule_table)

    def are_partitioned(self, sender_node_id, receiver_node_id):
        return self.partition[sender_node_id] != self.partition[receiver_node_id]

    def _load_rules_from_encoding(self):
        self.delay_rule_table.clear()
        self.byzz_rule_table.clear()

        for rule in self.encoding["delay_rules"]:
            # expected: [seq, from_node, to_node, "TMProposeSet", delay]
            assert len(rule) == 5, f"Invalid delay rule format: {rule}"
            seq, from_node, to_node, msg_type, delay = rule
            # 获取msg_type对应的class
            msg_type = getattr(ripple_pb2, str(msg_type))

            key = (int(seq), int(from_node), int(to_node), msg_type)
            self.delay_rule_table[key] = int(delay)

        for rule in self.encoding["byzz_rules"]:
            # expected: [seq, to_node, "TMValidation", "drop"]
            assert len(rule) == 4, f"Invalid byzz rule format: {rule}"
            seq, to_node, msg_type, method = rule
            msg_type = getattr(ripple_pb2, str(msg_type))
            key = (int(seq), int(to_node), msg_type)
            self.byzz_rule_table[key] = str(method)

    def setup(self):
        if self.partition and len(self.partition) != self.network.node_amount:
            raise ValueError(
                f"partition length {len(self.partition)} != node amount {self.network.node_amount}"
            )

    def get_partition_delay(
        self,
        cur_time: float,
    ) -> int:
        # do not lock this function!
        # this function assumes two nodes are partitioned
        start = self.partition_start_time
        if start is None:
            return 0
        else:
            return int(
                (self.partition_start_time * 1000 + self.partition_duration)
                - (cur_time * 1000)
            )

    def get_delay(
        self,
        message_type: int,
        packet: packet_pb2.Packet,
        current_ledger: int,
        message_cls: type,
    ) -> int:

        sender_node_id = self.network.port_to_id(packet.from_port)
        receiver_node_id = self.network.port_to_id(packet.to_port)

        keys = (current_ledger, sender_node_id, receiver_node_id, message_cls)

        if keys in self.delay_rule_table:
            ruled_delay = self.delay_rule_table[keys]
        else:
            ruled_delay = 0

        cur_time = time.time()  # returns seconds in float
        # 先设置partition_start_time标志，再决定延时

        with self.partition_lock:
            if self.partition_start_time is not None:
                if (
                    cur_time - self.partition_start_time
                    >= self.encoding["partition_duration"] / 1000.0
                ):
                    # 超出持续时间，重置分区状态
                    self.partition_start_time = None
            elif current_ledger == self.partition_seq:
                self.partition_start_time = cur_time

        with self.partition_lock:
            if self.partition_start_time is None:
                # logger.error(f"{sender_node_id}->{receiver_node_id} are not partitioned, ruled delay at ledger {current_ledger} for message type {message_cls.__name__} is {ruled_delay} ms") if ruled_delay > 0 else None
                return ruled_delay
            elif self.are_partitioned(sender_node_id, receiver_node_id):
                delay = self.get_partition_delay(cur_time)
                # logger.error(f"message from {sender_node_id} to {receiver_node_id} is partitioned, current ledger: {current_ledger}, partition seq: {self.partition_seq}, partition duration: {self.partition_duration} ms, time since partition start: {(cur_time - self.partition_start_time)*1000} ms, delay set to: {delay} ms")
                return delay  # remaining time in ms
            else:
                return 0

    def get_mutation_method(
        self,
        message,
        packet: packet_pb2.Packet | None = None,
        current_ledger: int | None = None,
    ) -> str:
        to_node_id = self.network.port_to_id(packet.to_port)
        msg_type = type(message)
        keys = (current_ledger, to_node_id, msg_type)
        if keys in self.byzz_rule_table:
            method = self.byzz_rule_table[keys]
            # logger.error("byzz rule hit: key={}, method={}", keys, method)
            return method
        return "do_nothing"


# random delay, random byzz
class RandomDelayByzzStrategy(EvoDelayStrategy):

    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.delay_max = self.params.get("max_delay_ms", 100)
        self.delay_min = self.params.get("min_delay_ms", 1)

    def setup(self):
        pass

    def get_delay(
        self,
        message_type: int,
        packet: packet_pb2.Packet,
        current_ledger: int,
        message_cls: type,
    ) -> int:
        # randomly choose a delay between min and max
        delay = random.randint(self.delay_min, self.delay_max)
        return delay


# random delay, random byzz, random partition with fixed starting seq and duration
class RandomDelayByzzPartitionStrategy(EvoDelayStrategy):
    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.delay_max = self.params.get("max_delay_ms", 100)
        self.delay_min = self.params.get("min_delay_ms", 1)
        self.partition_start_time = None
        self.partition_lock = threading.Lock()
        self.partition_seq = self.encoding["partition_seq"]
        self.partition_duration = self.encoding["partition_duration"]
        self.partition = None

    def _gen_partition(self):
        num_nodes = self.network.node_amount
        partition = list(range(num_nodes))
        random.shuffle(partition)
        # 生成一个随机的分区，返回一个列表，前半部分是一个分区，后半部分是另一个分区
        cut = random.randint(1, num_nodes - 1)
        partition = (set(partition[:cut]), set(partition[cut:]))
        # logger.error(f"Generated random partition: {partition} at seq {self.partition_seq}, duration {self.partition_duration} ms")
        return partition

    def are_partitioned(self, sender_node_id, receiver_node_id):
        if self.partition is None:
            return False
        for parts in self.partition:
            if sender_node_id in parts and receiver_node_id in parts:
                return False
        return True

    def setup(self):
        self.partition_start_time = None
        self.partition = None

    def get_partition_delay(self, cur_time) -> int:
        # do not lock this function!
        start = self.partition_start_time
        if start is None:
            return 0
        else:
            return int(
                (self.partition_start_time * 1000 + self.partition_duration)
                - (cur_time * 1000)
            )

    def get_delay(
        self,
        message_type: int,
        packet: packet_pb2.Packet,
        current_ledger: int,
        message_cls: type,
    ) -> int:

        sender_node_id = self.network.port_to_id(packet.from_port)
        receiver_node_id = self.network.port_to_id(packet.to_port)

        random_delay = random.randint(self.delay_min, self.delay_max)
        cur_time = time.time()  # returns seconds in float
        # 先设置partition_start_time标志，再决定延时

        with self.partition_lock:
            if self.partition_start_time is not None:
                if (
                    cur_time - self.partition_start_time
                    >= self.encoding["partition_duration"] / 1000.0
                ):
                    # 超出持续时间，重置分区状态
                    self.partition_start_time = None
                    self.partition = None
            elif current_ledger == self.partition_seq:
                self.partition_start_time = cur_time
                self.partition = self._gen_partition()

        with self.partition_lock:
            if self.partition_start_time is None:
                return random_delay
            elif self.are_partitioned(sender_node_id, receiver_node_id):
                delay = self.get_partition_delay(cur_time)
                # logger.error(f"message from {sender_node_id} to {receiver_node_id} is partitioned, current ledger: {current_ledger}, partition seq: {self.partition_seq}, partition duration: {self.partition_duration} ms, time since partition start: {(cur_time - self.partition_start_time)*1000} ms, delay set to: {delay} ms")
                return delay  # remaining time in ms
            else:
                return random_delay


# no delay, random byzz
class RandomByzzStrategy(EvoDelayStrategy):
    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(**kwargs)

    def setup(self):
        # RandomByzzStrategy does not use encoded delays.
        pass

    def get_delay(
        self,
        message_type: int,
        packet: packet_pb2.Packet,
        current_ledger: int,
        message_cls: type,
    ) -> int:
        return 0


# random delay, no byzz
class RandomDelayStrategy(EvoDelayStrategy):

    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.delay_max = self.params.get("max_delay_ms", 100)
        self.delay_min = self.params.get("min_delay_ms", 1)

    def setup(self):
        # RandomDelayStrategy uses random delay bounds, not encoded delays.
        pass

    def get_delay(
        self,
        message_type: int,
        packet: packet_pb2.Packet,
        current_ledger: int,
        message_cls: type,
    ) -> int:
        # randomly choose a delay between min and max
        delay = random.randint(self.delay_min, self.delay_max)
        return delay

    def get_mutation_method(
        self,
        message,
        packet: packet_pb2.Packet | None = None,
        current_ledger: int | None = None,
    ):
        return "do_nothing"


# encoded delay by seq, random byzz
class EvoDelayBySeqStrategy(EvoDelayStrategy):
    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.num_seqs = self.byzz_max_seq - self.byzz_min_seq + 1
        logger.info(
            f"Initialized EvoDelayBySeqStrategy with byzz_min_seq: {self.byzz_min_seq}, byzz_max_seq: {self.byzz_max_seq}, num_seqs: {self.num_seqs}"
        )

    def setup(self):
        logger.info(f"self.encoding = {self.encoding}")
        encoding_len = len(self.encoding["delays"])
        encoding_expected_len = (
            7
            * self.network.node_amount
            * (self.network.node_amount - 1)
            * self.num_seqs
        )

        assert encoding_len == encoding_expected_len

    def get_delay(
        self,
        message_type: int,
        packet: packet_pb2.Packet,
        current_ledger: int,
        message_cls: type,
    ) -> int:

        sender_node_id = self.network.port_to_id(packet.from_port)
        receiver_node_id = self.network.port_to_id(packet.to_port)
        type_id = message_type - 30 if message_type != 41 else 6
        seq_id = current_ledger - self.byzz_min_seq
        if seq_id < 0 or seq_id > self.num_seqs:
            return 0
        index = (
            seq_id
            * type_id
            * (self.network.node_amount * (self.network.node_amount - 1))
            + sender_node_id * (self.network.node_amount - 1)
            + (
                receiver_node_id
                if receiver_node_id < sender_node_id
                else receiver_node_id - 1
            )
        )

        assert index < len(
            self.encoding["delays"]
        ), f"Index out of bounds: {index}, encoding length: {len(self.encoding['delays'])}"
        return self.encoding["delays"][index]
