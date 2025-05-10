"""This module contains the class that implements a strategy which can handle delay-based evolutionary encodings."""

import random
import struct
from typing import Any, Dict, Tuple

from protos import packet_pb2
from rocket_controller.encoder_decoder import DecodingNotSupportedError, PacketEncoderDecoder
from rocket_controller.helper import MAX_U32
from rocket_controller.iteration_type import TimeBasedIteration
from rocket_controller.strategies.strategy import Strategy


class EvoDelayStrategy(Strategy):
    """Class that implements an evolutionary delay-based strategy."""

    def __init__(
        self,
        network_config_path: str = "./config/network/default_network.yaml",
        strategy_config_path: str | None = None,
        # auto_partition: bool = True,
        auto_parse_identical: bool = False,
        auto_parse_subsets: bool = False,
        # keep_action_log: bool = True,
        iteration_type: TimeBasedIteration | None = None,
        network_overrides: Dict[str, Any] | None = None,
        strategy_overrides: Dict[str, Any] | None = None,
    ):
        """
        Initializes the EvoDelayStrategy.

        Args:
            network_config_path: The path to a network config file to be used.
            strategy_config_path: The path to a strategy config file to be used.
            auto_parse_identical: Whether to auto-parse identical packages per peer combination.
            auto_parse_subsets: Whether to auto-parse identical packages w.r.t. defined subsets.
            iteration_type: The type of iteration to keep track of.
            network_overrides: A dictionary containing parameter names and values which override the network config.
            strategy_overrides: A dictionary containing parameter names and values which override the strategy config.
        """
        super().__init__(
            network_config_path=network_config_path,
            strategy_config_path=strategy_config_path,
            auto_parse_identical=auto_parse_identical,
            auto_parse_subsets=auto_parse_subsets,
            iteration_type=iteration_type,
            network_overrides=network_overrides,
            strategy_overrides=strategy_overrides,
        )

        # Relies on correct processing -> encoding should be of correct length
        self.delays: list[int] = self.params['encoding']

        # for n nodes
        # index = num(message_type) * (n * n-1) + from_id * (n-1) + conditional(to_id)
        # conditional(to_id) -> if to_id is larger than from_id, return to_id-1, else return to_id.

    def setup(self):
        """Setup method for EvoDelayStrategy."""

        # Hardcoded on 7 message types we will consider, could be a parameter in the future
        assert len(self.delays) == 7 * self.network.node_amount * (self.network.node_amount-1)

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int, int]:
        """
        Implements the handle_packet method with an encoding of delays.

        Args:
            packet: The original packet to be sent.

        Returns:
            Tuple[bytes, int, int]: The new packet, the delay and the send amount.
        """

        # Code taken from packet decoder
        message_type = struct.unpack("!H", packet.data[4:6])[0]

        if message_type not in set(range(30, 36)).union({41}):
            return packet.data, 0, 1

        # Types used in evolutionary paper: https://doi.org/10.1109/ICSE-SEIP58684.2023.00009
        # 30: ripple_pb2.TMTransaction
        # 31: ripple_pb2.TMGetLedger
        # 32: ripple_pb2.TMLedgerData
        # 33: ripple_pb2.TMProposeSet
        # 34: ripple_pb2.TMStatusChange
        # 35: ripple_pb2.TMHaveTransactionSet
        # 41: ripple_pb2.TMValidation

        # To get type index -> subtract 30, for validation, subtract 35
        type_id = message_type - 30 if message_type != 41 else 6
        sender_node_id = self.network.port_to_id(packet.from_port)
        receiver_node_id = self.network.port_to_id(packet.to_port)

        # for n nodes
        # index = num(message_type) * (n * n-1)
        #           + from_id * (n-1)
        #           + conditional(to_id)
        # conditional(to_id) -> if to_id is larger than from_id, return to_id-1, else return to_id.

        index = (type_id * (self.network.node_amount * (self.network.node_amount-1))
                 + sender_node_id * (self.network.node_amount-1)
                 + (receiver_node_id if receiver_node_id < sender_node_id else receiver_node_id - 1))

        # Get index through a default function
        # Return with delay=self.delays[index]

        return packet.data, self.delays[index], 1
