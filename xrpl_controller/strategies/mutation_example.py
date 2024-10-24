"""This module contains the class that implements an example Strategy using simple mutation."""

from datetime import datetime
from typing import Tuple

from xrpl.utils import datetime_to_ripple_time

from protos import packet_pb2, ripple_pb2
from xrpl_controller.iteration_type import TimeBasedIteration
from xrpl_controller.strategies.encoder_decoder import (
    DecodingNotSupportedError,
    PacketEncoderDecoder,
)
from xrpl_controller.strategies.strategy import Strategy


class MutationExample(Strategy):
    """Class that Mutates all TMProposeSet messages."""

    def __init__(self, iteration_type: TimeBasedIteration | None = None):
        """Initialize the MutationExample class."""
        super().__init__(iteration_type=iteration_type)

    def setup(self):
        """Setup method for MutationExample."""

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int]:
        """
        Handler method for receiving a packet.

        Args:
            packet: Packet to handle.

        Returns:
            Tuple[bytes, int]: A tuple of the possible mutated message as bytes, and action as int
        """
        # Decode the packet to figure out the type and length
        try:
            message, message_type_no = PacketEncoderDecoder.decode_packet(packet)
        except DecodingNotSupportedError:
            return packet.data, 0

        # Check whether message is of type TMProposeSet
        if not isinstance(message, ripple_pb2.TMProposeSet):
            return packet.data, 0

        # Mutate the closeTime of each message
        message.closeTime = datetime_to_ripple_time(datetime.now())

        # Sign the message
        signed_message = PacketEncoderDecoder.sign_message(
            message,
            self.network.public_to_private_key_map[message.nodePubKey.hex()],
        )

        return PacketEncoderDecoder.encode_message(signed_message, message_type_no), 0
