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
from rocket_controller.strategies.strategy import Strategy
from xrpl.core.keypairs.secp256k1 import SECP256K1, sha512_first_half

import serialize
import re
from pathlib import Path
from loguru import logger



class RandomByzzStrategy(Strategy):
    
    def __init__(
        self,
        network_config_path: str = "./config/network/default_network.yaml",
        **kwargs,
    ):
        super().__init__(network_config_path=network_config_path, **kwargs)
        self.byzz_nodes: list[int] = self.network.network_config.get("byzz_nodes", [])
        
        
    def setup(self):
        """Setup method for EvoDelayStrategy."""

        # Hardcoded on 7 message types we will consider, could be a parameter in the future
        assert len(self.delays) == 7 * self.network.node_amount * (
            self.network.node_amount - 1
        )
        
    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int, int]:
        raise NotImplementedError("handle_packet is not implemented in RandomByzzStrategy")