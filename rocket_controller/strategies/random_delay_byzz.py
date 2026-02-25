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
        self, message_type: int, packet: packet_pb2.Packet, current_ledger: int
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
        for parts in self.partition:
            if sender_node_id in parts and receiver_node_id in parts:
                return False
        return True

    def setup(self):
        pass

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
        self, message_type: int, packet: packet_pb2.Packet, current_ledger: int
    ) -> int:
        # NOTE: this function can only handle a single partition or partitions without overlapping duration
        # randomly choose a delay between min and max

        with self.partition_lock:
            if self.partition is None:
                self.partition = self._gen_partition()

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
            elif current_ledger == self.partition_seq:
                self.partition_start_time = cur_time

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

    def get_delay(self, message_type: int, packet: packet_pb2.Packet) -> int:
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

    def get_delay(self, message_type: int, packet: packet_pb2.Packet) -> int:
        # randomly choose a delay between min and max
        delay = random.randint(self.delay_min, self.delay_max)
        return delay

    def get_mutation_method(self, message):
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
        self, message_type: int, packet: packet_pb2.Packet, current_ledger: int
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
