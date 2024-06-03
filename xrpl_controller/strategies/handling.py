import struct
from typing import Tuple, List
from protos import packet_pb2
from xrpl_controller.strategies.strategy import Strategy
from xrpl_controller.validator_node_info import ValidatorNode
from xrpl_controller.strategies.Decoder import PacketDecoder
from xrpl_controller.strategies.PacketMutator import PacketMutator




class Handling(Strategy):
    """Class that handles specific packets."""

    def __init__(self, send_probability, drop_probability, min_delay_ms, max_delay_ms):
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
        message, message_type, length, private_key_from = self.decoder.decode_packet(packet)



        try:
            mutated_message_bytes = self.mutator.mutate_packet(message, message_type, private_key_from)
            print(f"mutated_message_bytes: {mutated_message_bytes}")
            changed_packet = struct.pack("!I", length) + struct.pack("!H", message_type) + mutated_message_bytes
            print(f"changed_packet: {changed_packet}")
            return changed_packet.data, 0
        except Exception as e:
            print("PAcket is None")
            print(f"packed data {packet.data}")
            return packet.data, 0


