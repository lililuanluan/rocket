"""This module contains the class that implements a Decoder."""

import struct
from functools import singledispatchmethod

from google.protobuf.message import Message
from xrpl.core.keypairs.secp256k1 import SECP256K1

from protos import packet_pb2, ripple_pb2
from protos.ripple_pb2 import TMProposeSet


class DecodingNotSupportedError(Exception):
    """Signals that decoding a certain message is not supported."""

    pass


# noinspection PyNestedDecorators
class PacketEncoderDecoder:
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
        # 50: Is not defined in proto file and has no corresponding class, but appears in enum.
        # 51: Is not defined in proto file and has no corresponding class, but appears in enum.
        52: ripple_pb2.TMGetPeerShardInfo,
        53: ripple_pb2.TMPeerShardInfo,
        54: ripple_pb2.TMValidatorList,
        55: ripple_pb2.TMSquelch,
        56: ripple_pb2.TMValidatorListCollection,
        57: ripple_pb2.TMProofPathRequest,
        58: ripple_pb2.TMProofPathResponse,
        59: ripple_pb2.TMReplayDeltaRequest,
        60: ripple_pb2.TMReplayDeltaResponse,
        61: ripple_pb2.TMGetPeerShardInfoV2,
        62: ripple_pb2.TMPeerShardInfoV2,
        63: ripple_pb2.TMHaveTransactions,
        64: ripple_pb2.TMTransactions,
    }

    @singledispatchmethod
    @staticmethod
    def sign_message(message: Message, private_key: str) -> Message:
        """
        Method that returns a signed version of a message.

        Args:
            message: Message to be signed.
            private_key: Private key of the message in hex format.
        """
        raise NotImplementedError(f"No signing method implemented for {type(message)}.")

    @sign_message.register
    @staticmethod
    def _(message: TMProposeSet, private_key: str) -> TMProposeSet:
        """
        Method that returns a signed version of a message.

        Args:
            message: Message to be signed.
            private_key: Private key of the message in hex format.
        """
        # Collect the fields used to originally sign the message
        bytes_to_sign = (
            b"\x50\x52\x50\x00"
            + message.proposeSeq.to_bytes(4, "big")
            + message.closeTime.to_bytes(4, "big")
            + message.previousledger
            + message.currentTxHash
        )

        # Sign the message using the private key
        signature = SECP256K1.sign(bytes_to_sign, private_key)

        # Update the message signature to the new signature
        message.signature = signature
        return message

    @staticmethod
    def decode_packet(packet: packet_pb2.Packet) -> tuple[Message | bytes, int]:
        """
        Decodes the given packet into a tuple.

        Args:
            packet:  packet to decode

        Returns:
            tuple of the message, and message type
        """
        # length = struct.unpack("!I", packet.data[:4])[0]
        message_type = struct.unpack("!H", packet.data[4:6])[0]
        if message_type not in PacketEncoderDecoder.message_type_map:
            raise DecodingNotSupportedError(
                f"Decoding of message type {message_type} not supported"
            )

        message_payload = packet.data[6:]
        message_class = PacketEncoderDecoder.message_type_map[message_type]
        message = message_class()
        message.ParseFromString(message_payload)
        return message, message_type

    @staticmethod
    def encode_message(message: Message, message_type: int) -> bytes:
        """
        Encode a message to its bytes representation, adding the correct headers.

        This function supports method overloading, using the @singledispatchmethod decorator.

        Args:
            message: message to encode
            message_type: type of message
        """
        # Serialize message to prepare sending to the interceptor
        serialized = message.SerializeToString()

        # Add headers containing the message length and type
        final_message = (
            int(len(serialized.hex()) / 2).to_bytes(4, "big")
            + message_type.to_bytes(2, "big")
            + serialized
        )
        return final_message
