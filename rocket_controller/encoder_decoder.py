"""This module contains the class that implements an encoder and a decoder for XRPL packets."""

import struct
from functools import singledispatchmethod

from google.protobuf.message import Message
from xrpl.core.keypairs.secp256k1 import SECP256K1

from protos import packet_pb2, ripple_pb2
from protos.ripple_pb2 import TMProposeSet, TMValidation
from typing import Any, Dict, Tuple
import serialize
import hashlib
import base58  # or bs58, depending on your environment
import re


def sha512_first_half(data: bytes) -> bytes:
    """Return the first 32 bytes of SHA-512(data).

    This reproduces XRPL's sha512Half behaviour (also called sha512_first_half
    elsewhere). The project dependency you tried to import it from may not
    expose this helper, so define it locally to avoid the missing import.
    """
    return hashlib.sha512(data).digest()[:32]


class DecodingNotSupportedError(Exception):
    """Signals that decoding a certain message is not supported."""

    pass


class ValidationDict(dict):
    """A thin wrapper around dict used to represent a parsed validation.

    This type exists so `PacketEncoderDecoder.sign_message` can be
    singledispatchable on the parsed validation representation.
    """
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
            private_key: Private key of the original sender of the message in hex format.

        Returns:
            Message: Signed Message.
        """
        raise NotImplementedError(f"No signing method implemented for {type(message)}.")



    # New API: accept a parsed ValidationDict and a private key, and return
    # a signed TMValidation. This avoids callers needing to re-parse the
    # serialized bytes and centralizes canonical serialization in one place.
    @sign_message.register(ValidationDict)
    @staticmethod
    def _(parsed: ValidationDict, private_key: str) -> TMValidation:
        # Build signing dict (exclude Signature)
        try:
            signing_dict = {k: v for k, v in parsed.items() if k != "Signature"}
            serialized = serialize.serialize_bytes(signing_dict)
            mutated_validation = bytes(serialized)
        except Exception as e:
            raise ValueError(f"serialize.serialize_bytes failed for parsed validation: {e}")

        # Prepare payload to sign
        bytes_to_sign = b"VAL\x00" + mutated_validation

        # Enforce single private-key format: hex string. Do not accept base58
        # here to avoid multiple decoding schemes. The network mapping stores
        # private keys as hex (see NetworkManager.update_network).
        if not all(c in "0123456789abcdefABCDEF" for c in private_key):
            raise ValueError("private_key must be a hex string; base58 is not supported here")
        private_key_hex = private_key

        try:
            der_sig = SECP256K1.sign(bytes_to_sign, private_key_hex)
            if isinstance(der_sig, str):
                der_sig_bytes = bytes.fromhex(der_sig)
            else:
                der_sig_bytes = der_sig
        except Exception as e:
            raise ValueError(f"Failed to sign validation from parsed dict: {e}")

        final_validation = (
            mutated_validation
            + bytes.fromhex("76")
            + len(der_sig_bytes).to_bytes(1, "big")
            + der_sig_bytes
        )

        tm = TMValidation()
        tm.validation = final_validation
        return tm

    @sign_message.register
    @staticmethod
    def _(message: TMProposeSet, private_key: str) -> TMProposeSet:
        """
        Method that takes in a ProposeSet and updates its signature.

        Args:
            message: ProposeSet.
            private_key: Private key of the original sender of the message in hex format.

        Returns:
            TMProposeSet: Message that needs to be signed
        """
        # Acquire the fields used to originally sign the message
        bytes_to_sign = (
            b"\x50\x52\x50\x00"
            + message.proposeSeq.to_bytes(4, "big")
            + message.closeTime.to_bytes(4, "big")
            + message.previousledger
            + message.currentTxHash
        )

        # Enforce private_key is hex-only (no base58 fallback)
        if not all(c in "0123456789abcdefABCDEF" for c in private_key):
            raise ValueError("private_key must be a hex string for ProposeSet signing")

        # Sign the message using the private key
        signature = SECP256K1.sign(bytes_to_sign, private_key)

        # Update the message signature to the new signature
        message.signature = signature
        return message

    @staticmethod
    def decode_packet(packet: packet_pb2.Packet) -> tuple[Message, int]:
        """
        Decodes a given packet into a tuple containing the message object and type number.

        Args:
            packet: Packet to decode.

        Returns:
            tuple[Message, int]: Tuple of the message, and message type.

        Raises:
            DecodingNotSupportedError: If the given packet is not supported.
        """
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
            message: Message to encode
            message_type: Type of message

        Returns:
            bytes: Encoded message.
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

    @staticmethod
    def decode_validation(validation_message) -> Dict[str, Any]:
        """
        Parse the content of a validation message using the Rust serialize library.

        Args:
            validation_message: The TMValidation protobuf message (= packet.data[6:] = PacketEncoderDecoder.decode_packet(packet)[0] )

        Returns:
            Dict with parsed validation fields, or empty dict if parsing fails
        """

        try:
            # Get the validation data from the protobuf message
            validation_data = validation_message.validation

            # Use the Rust parse_bytes function to parse the validation data
            parsed = serialize.parse_bytes(validation_data)

            # Return a ValidationDict so callers can mutably modify it and
            # PacketEncoderDecoder.sign_message can dispatch on the type.
            return ValidationDict(parsed)
        except Exception as e:
            return ValidationDict({"error": f"Failed to parse validation: {str(e)}"})
