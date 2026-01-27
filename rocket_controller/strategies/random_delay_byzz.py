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


class RandomByzzStrategy(EvoDelayStrategy):

    def __init__(
        self,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.delay_max = self.params.get("max_delay_ms", 100)
        self.delay_min = self.params.get("min_delay_ms", 1)

    def get_delay(self,message_type: int, packet: packet_pb2.Packet) -> int:
        # randomly choose a delay between min and max
        delay = random.randint(self.delay_min, self.delay_max)
        return delay