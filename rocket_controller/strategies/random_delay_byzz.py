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

    def get_delay(self, message_type: int, packet: packet_pb2.Packet) -> int:
        # randomly choose a delay between min and max
        delay = random.randint(self.delay_min, self.delay_max)
        return delay


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

        assert (encoding_len == encoding_expected_len)

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
