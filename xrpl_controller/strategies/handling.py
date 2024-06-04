"""This module contains the class that implements a handling."""

from typing import Tuple

from protos import packet_pb2
from xrpl_controller.strategies.Decoder import PacketDecoder
from xrpl_controller.strategies.PacketMutator import PacketMutator
from xrpl_controller.strategies.strategy import Strategy


class Handling(Strategy):
    """Class that handles specific packets."""

    def __init__(self, send_probability, drop_probability, min_delay_ms, max_delay_ms):
        """
        Implements the initialization of PacketHandler.

        Args:
           send_probability (float): Probability of sending the packet
           drop_probability (float): Probability of dropping the packet
           min_delay_ms (float): Minimum delay in milliseconds
           max_delay_ms (float): Maximum delay in milliseconds
           private_key: Private key of the node
           validator_list: List of validator nodes
        """
        super().__init__()
        self.send_probability = send_probability
        self.drop_probability = drop_probability
        self.min_delay_ms = min_delay_ms
        self.max_delay_ms = max_delay_ms
        self.mutator = PacketMutator()
        self.decoder = PacketDecoder()

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int]:
        """
        Handle a single packet.

        Args:
            packet:  of the node

        Returns: Tuple of mutated packet and action

        """
        print(f"packet received: {packet}")
        message, message_type, length, private_key_from = self.decoder.decode_packet(
            packet
        )

        try:
            mutated_message_bytes = self.mutator.mutate_packet(
                message, message_type, private_key_from
            )
            print(f"\nmutated_message_bytes: {mutated_message_bytes}\n")
            # changed_packet = (
            #     struct.pack("!I", length)
            #     + struct.pack("!H", message_type)
            #     + mutated_message_bytes
            # ).Serialise
            print(f"\nchanged_packet: {packet}\n")
            return packet.data, 0
        except Exception:
            print("PAcket is None")
            print(f"packed data {packet.data!r}")
            return packet.data, 0
