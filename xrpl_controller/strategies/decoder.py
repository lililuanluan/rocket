"""This module contains the class that implements a Decoder."""

import struct

from google.protobuf.message import Message

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

    @staticmethod
    def decode_packet(packet: packet_pb2.Packet) -> tuple[Message | bytes, int]:
        """
        Decodes the given packet into a tuple.

        Args:
            packet:  packet to decode

        Returns:   tuple of message, type, length and private key
        """
        length = struct.unpack("!I", packet.data[:4])[0]
        message_type = struct.unpack("!H", packet.data[4:6])[0]
        message_payload = packet.data[6:]

        if message_type in PacketDecoder.message_type_map:
            message_class = PacketDecoder.message_type_map[message_type]
            message = message_class()
            message.ParseFromString(message_payload)
            return message, length

        return packet.data, length
