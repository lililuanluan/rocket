"""This module contains the class that implements a Decoder."""

import struct
from typing import Any

from protos import packet_pb2, ripple_pb2


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

    def decode_packet(self, packet: packet_pb2.Packet) -> tuple[Any, Any, Any]:
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

        if message_type in self.message_type_map:
            message_class = self.message_type_map[message_type]
            message = message_class()
            message.ParseFromString(message_payload)
            print(f"deserealised: {message}")
            print(f"type of message: {type(message)})")
            return message, message_type, length
        else:
            raise Exception("Invalid message type")
