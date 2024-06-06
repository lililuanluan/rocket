"""This module contains the class to quickly test and try different mutations to see if they reach consensus instead.

of needing to change three seperate files.
"""

import hashlib
import random
import struct
from typing import List, Tuple

import base58
from ecdsa.curves import SECP256k1  # type: ignore
from ecdsa.keys import SigningKey  # type: ignore

from protos import packet_pb2, ripple_pb2
from xrpl_controller.strategies.strategy import Strategy
from xrpl_controller.validator_node_info import ValidatorNode

MAX_U32 = 2**32 - 1
validator_node_list_store: List[ValidatorNode] = []
private_key_from = None


class SpecificPacketHandler(Strategy):
    """Class that implements a strategy for handling specific packets."""

    def __init__(self, send_probability, drop_probability, min_delay_ms, max_delay_ms):
        """Initialize the SpecificPacketHandler.

        Args:
            send_probability (float): The probability of sending a packet.
            drop_probability (float): The probability of dropping a packet.
            min_delay_ms (int): The minimum delay in milliseconds.
            max_delay_ms (int): The maximum delay in milliseconds.
        """
        super().__init__()
        self.send_probability = send_probability
        self.drop_probability = drop_probability
        self.min_delay_ms = min_delay_ms
        self.max_delay_ms = max_delay_ms

    @staticmethod
    def sha512_first_half(message: bytes) -> bytes:
        """Compute the SHA-512 hash of the first half of the message.

        Args:
            message (bytes): The input message.

        Returns:
            bytes: The SHA-512 hash of the first half of the message.
        """
        sha512 = hashlib.sha512()
        sha512.update(message)
        full_hash = sha512.digest()
        return full_hash[:32]

    def get_private_key(self, from_port: int) -> str:
        """Get the private key corresponding to the given port.

        Args:
            from_port (int): The port number.

        Returns:
            str: The private key corresponding to the port.
        """
        for node in validator_node_list_store:
            if node.peer.port == from_port:
                private_key_from = node.validator_key_data.validation_private_key
                return private_key_from
        print("Private key not found.")
        return "no private key"

    @staticmethod
    def sign_message(hash_bytes: bytes, private_key: bytes) -> bytes:
        """Sign the given message hash with the private key.

        Args:
            hash_bytes (bytes): The message hash.
            private_key (bytes): The private key.

        Returns:
            bytes: The signature.
        """
        signing_key = SigningKey.from_string(private_key, curve=SECP256k1)
        signature = signing_key.sign_digest(hash_bytes)
        return signature

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int]:
        """Handle incoming packets.

        Args:
            packet (packet_pb2.Packet): The incoming packet.

        Returns:
            Tuple[bytes, int]: A tuple containing the modified packet data and delay.
        """
        length = struct.unpack("!I", packet.data[:4])[0]
        message_type = struct.unpack("!H", packet.data[4:6])[0]
        message_payload = packet.data[6:]

        private_key_from = self.get_private_key(packet.from_port)

        message_type_maps = {
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

        if message_type in message_type_maps:
            message_class = message_type_maps[message_type]
            message = message_class()
            message.ParseFromString(message_payload)

            if (
                message_type == 33
                and random.random() <= 0.15
                and private_key_from != "no private key"
            ):  # 0.1% chance
                message.currentTxHash = bytes.fromhex(
                    "e803e1999369975aed1bfd2444a3552a73383c03a2004cb784ce07e13ebd7d7c"
                )

                hash_bytes = self.sha512_first_half(
                    b"".join(
                        [
                            b"\x50\x52\x50\x00",
                            message.proposeSeq.to_bytes(4, "big"),
                            message.closeTime.to_bytes(4, "big"),
                            message.previousledger,
                            message.currentTxHash,
                        ]
                    )
                )

                try:
                    priv_key = base58.b58decode(
                        private_key_from, alphabet=base58.XRP_ALPHABET
                    )
                    if len(priv_key) != 33:
                        raise ValueError("Invalid private key length")
                    actual_priv_key = priv_key[1:33]
                except ValueError as e:
                    print(f"Error decoding or validating private key: {e}")
                    return packet.data, 0

                signature = self.sign_message(hash_bytes, actual_priv_key)
                message.signature = signature

                changed_packet = (
                    struct.pack("!I", length)
                    + struct.pack("!H", message_type)
                    + message.SerializeToString()
                )
                return changed_packet, 0

        return packet.data, 0


def getKeys(validator_node_list: List[ValidatorNode]):
    """
    Implements a method to get the private key.

    Args:
        validator_node_list: List[ValidatorNode] List of validator nodes.

    Returns:
        str: this is the string of the private key
    """
    global validator_node_list_store
    validator_node_list_store = validator_node_list
    print(f"Validator list: {validator_node_list_store}")
