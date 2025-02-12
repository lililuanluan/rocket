"""This module contains the class that implements an example Strategy using simple mutation."""

from datetime import datetime
from typing import Any, Dict, Tuple

from xrpl.utils import datetime_to_ripple_time

from protos import packet_pb2, ripple_pb2
from rocket_controller.encoder_decoder import (
    DecodingNotSupportedError,
    PacketEncoderDecoder,
)
from rocket_controller.iteration_type import TimeBasedIteration
from rocket_controller.strategies.strategy import Strategy


class MutationExample(Strategy):
    """Class that Mutates all TMProposeSet messages."""

    def __init__(
        self,
        network_config_path: str = "./config/network/default_network.yaml",
        strategy_config_path: str | None = None,
        iteration_type: TimeBasedIteration | None = None,
        network_overrides: Dict[str, Any] | None = None,
        strategy_overrides: Dict[str, Any] | None = None,
    ):
        """Initialize the MutationExample class.

        Args:
            network_config_path: The path to a network config file to be used.
            strategy_config_path: The path to a strategy config file to be used.
            iteration_type: The type of iteration to keep track of.
            network_overrides: A dictionary containing parameter names and values which override the network config.
            strategy_overrides: A dictionary containing parameter names and values which override the strategy config.
        """
        super().__init__(
            network_config_path=network_config_path,
            strategy_config_path=strategy_config_path,
            iteration_type=iteration_type,
            network_overrides=network_overrides,
            strategy_overrides=strategy_overrides,
        )

    def setup(self):
        """Setup method for MutationExample."""

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int, int]:
        """
        Handler method for receiving a packet.

        Args:
            packet: Packet to handle.

        Returns:
            Tuple[bytes, int, int]: A tuple of the possible mutated message as bytes, an action as int and the send amount.
        """
        # Decode the packet to figure out the type and length
        try:
            message, message_type_no = PacketEncoderDecoder.decode_packet(packet)
        except DecodingNotSupportedError:
            return packet.data, 0, 1

        # Check whether message is of type TMProposeSet
        if not isinstance(message, ripple_pb2.TMProposeSet):
            return packet.data, 0, 1

        # Mutate the closeTime of each message
        message.closeTime = datetime_to_ripple_time(datetime.now())

        # Sign the message
        signed_message = PacketEncoderDecoder.sign_message(
            message,
            self.network.public_to_private_key_map[message.nodePubKey.hex()],
        )

        return (
            PacketEncoderDecoder.encode_message(signed_message, message_type_no),
            0,
            1,
        )
