"""This module contains the class that implements a handling."""

from datetime import datetime
from typing import Tuple

from xrpl.core.keypairs.secp256k1 import SECP256K1
from xrpl.utils.time_conversions import datetime_to_ripple_time

from protos import packet_pb2, ripple_pb2
from xrpl_controller.strategies.encoder_decoder import (
    DecodingNotSupportedError,
    PacketEncoderDecoder,
)
from xrpl_controller.strategies.strategy import Strategy


class MutationExample(Strategy):
    """Class that Mutates all TMProposeSet messages."""

    def __init__(self):
        """Initialize the MutationExample class."""
        super().__init__()

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int]:
        """
        Handler method for receiving a packet.

        Args:
            packet:  of the node

        Returns:
            A tuple of the possible mutated message as bytes, and action as int
        """
        # Decode the packet to figure out the type and length
        try:
            message, message_type_no = PacketEncoderDecoder.decode_packet(packet)
        except DecodingNotSupportedError:
            return packet.data, 0

        # check whether message is of type TMProposeSet
        if not isinstance(message, ripple_pb2.TMProposeSet):
            return packet.data, 0

        # Cast variable to use its fields
        propose_set_msg: ripple_pb2.TMProposeSet = message

        # Mutate the closeTime of each message
        propose_set_msg.closeTime = datetime_to_ripple_time(datetime.now())

        # Collect the fields used to originally sign the message
        bytes_to_sign = (
            b"\x50\x52\x50\x00"
            + propose_set_msg.proposeSeq.to_bytes(4, "big")
            + propose_set_msg.closeTime.to_bytes(4, "big")
            + propose_set_msg.previousledger
            + propose_set_msg.currentTxHash
        )

        # Get the private key belonging to the public key field in the message
        private_key = self.public_to_private_key_map[propose_set_msg.nodePubKey.hex()]

        # Sign the message using the private key
        signature = SECP256K1.sign(bytes_to_sign, private_key)

        # Update the message signature to the new signature
        propose_set_msg.signature = signature

        return PacketEncoderDecoder.encode_message(propose_set_msg, message_type_no), 0
