"""This module contains the class that implements a Decoder."""

import struct
from typing import Any, List

from protos import packet_pb2, ripple_pb2
from xrpl_controller.validator_node_info import ValidatorNode

validator_node_list_store: List[ValidatorNode] = []
private_key_from = None


class PacketDecoder:
    """Class that implements a packet decoder."""

    message_type_map = {
        2: ripple_pb2.TMManifests,
        3: ripple_pb2.TMPing,
        5: ripple_pb2.TMCluster,
        15: ripple_pb2.TMEndpoints,
        30: ripple_pb2.TMTransaction,
        31: ripple_pb2.TMGetLedger,
        32: ripple_pb2.TMLedgerData,
        33: ripple_pb2.TMProposeSet,
        34: ripple_pb2.TMStatusChange,
        35: ripple_pb2.TMHaveTransactionSet,
        41: ripple_pb2.TMValidation,
        42: ripple_pb2.TMGetObjectByHash,
    }

    def get_private_key(self, from_port: int) -> str:
        """
            Gets the private key from the given port.

        Args:
            from_port: int fo the port

        Returns: private key

        """
        for node in validator_node_list_store:
            print(f"from port {from_port} peer port: {node.peer.port}")
            if node.peer.port == from_port:
                private_key_from = node.validator_key_data.validation_private_key
                print(f"private key {private_key_from}")
                return private_key_from
        print("Private key not found.")
        return "no private key"

    def decode_packet(self, packet: packet_pb2.Packet) -> tuple[Any, Any, Any, str]:
        """
        Decodes the given packet into a tuple.

        Args:
            packet:  packet to decode

        Returns:   tuple of message, type, length and private key

        """
        print(f"Received packet {packet}")

        length = struct.unpack("!I", packet.data[:4])[0]
        message_type = struct.unpack("!H", packet.data[4:6])[0]
        message_payload = packet.data[6:]
        print(f"length: {length}")
        print(f"Message type {message_type}")

        if message_type in PacketDecoder.message_type_map:
            message_class = PacketDecoder.message_type_map[message_type]
            message = message_class()
            message.ParseFromString(message_payload)
            print(f"deserealised: {message}")
            private_key_from = self.get_private_key(packet.from_port)
            return message, message_type, length, private_key_from
        else:
            raise Exception("Invalid message type")


def checkList(validator_node_list: List[ValidatorNode]):
    """
    returns the updated validator_node_list.

    Args:
        validator_node_list: List with all the validator nodes

    Returns: nothing

    """
    global validator_node_list_store

    validator_node_list_store = validator_node_list
