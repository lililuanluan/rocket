"""This module contains the class that implements a Packet handling."""

import hashlib
import struct
from typing import List, Tuple

import base58  # type: ignore
import secp256k1  # type: ignore
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from google.protobuf import message

from protos import packet_pb2, ripple_pb2
from xrpl_controller.strategies.strategy import Strategy
from xrpl_controller.validator_node_info import ValidatorNode

MAX_U32 = 2**32 - 1
validator_node_list_store: List[ValidatorNode] = []
private_key_from = None


class PacketHandler(Strategy):
    """Class that implements random fuzzer."""

    def __init__(
        self,
        send_probability,
        drop_probability,
        min_delay_ms,
        max_delay_ms,
        private_key,
        validator_list,
    ):
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
        self.send_probability = send_probability
        self.drop_probability = drop_probability
        self.min_delay_ms = min_delay_ms
        self.max_delay_ms = max_delay_ms
        self.private_key = private_key
        self.validator_list = validator_list

    def getKey(self, validator_node_list: List[ValidatorNode]) -> str:
        """
        Implements a method to get the private key.

        Args:
            validator_node_list: List[ValidatorNode] List of validator nodes.

        Returns:
            str: this is the string of the private key
        """
        self.validator_list = validator_node_list
        print(f"Stored validator info: {self.validator_list}")

        for node in self.validator_list:
            print(f"Stored validator: {node}")
            if node.ws_public.port == 61000:
                private_key = node.validator_key_data.validation_private_key
                self.private_key = private_key
                print(f"Private key: {self.private_key}")
                return self.private_key

        return "no_key"

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int]:
        """
        Implements the handle_packet method with a random action.

        Args:
            packet: the original packet to be sent.

        Returns:
            Tuple[bytes, int]: the new packet and the random action.
        """
        print(f"\nReceived packet: {packet}\n")
        length = struct.unpack("!I", packet.data[:4])[0]
        print(f"Message length: {length}")

        message_type = struct.unpack("!H", packet.data[4:6])[0]
        print(f"Message type: {message_type!r}")
        message_payload = packet.data[6:]
        print(f"Message data: {message_payload!r}")

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

        self.message_type_name_map = {
            v: k
            for k, v in {
                2: "TMManifests",
                3: "TMPing",
                5: "TMCluster",
                15: "TMEndpoints",
                30: "TMTransaction",
                31: "TMGetLedger",
                32: "TMLedgerData",
                33: "TMProposeSet",
                34: "TMStatusChange",
                35: "TMHaveTransactionSet",
                41: "TMValidation",
                42: "TMGetObjectByHash",
            }.items()
        }

        if message_type in message_type_map:
            message_class = message_type_map[message_type]
            message = message_class()
            message.ParseFromString(message_payload)
            print(f"\nMessage type: {message_class}")
            print(f"Deserialized message: {message}")

            if message_type == 33:  # TMProposeSet
                message.currentTxHash = bytes.fromhex(
                    "e803e1999369975aed1bfd2444a3552a73383c03a2004cb784ce07e13ebd7d7c"
                )
                print(f"Tx Hash changed with message original: {message}")

                def sha512_first_half(data: bytes) -> bytes:
                    hash_bytes = hashlib.sha512(data).digest()
                    return hash_bytes[:32]

                def sign_message(hash_bytes: bytes, private_key: bytes) -> bytes:
                    ctx = secp256k1.PrivateKey(private_key)
                    signature = ctx.ecdsa_sign(hash_bytes)
                    return ctx.ecdsa_serialize_der(signature)

                hash_bytes = sha512_first_half(
                    b"".join(
                        [
                            b"\x50\x52\x50\x00",
                            message.closeTime.to_bytes(4, "big"),
                            message.previousledger,
                            message.currentTxHash,
                        ]
                    )
                )

                priv_key = base58.b58decode(self.private_key)
                signature = sign_message(hash_bytes, priv_key[1:33])

                message.signature = signature
                message_bytes = message.SerializeToString()

                print(f"Message bytes: {message_bytes}")
                print(f"Signature final: {signature!r}")
        else:
            print(f"Unknown message type: {message_type}")

        return packet.data, 0


def load_private_key_from_base58(private_key_base58: str) -> rsa.RSAPrivateKey | None:
    """
    Loads a private key from a base58-encoded string.

    Args:
        private_key_base58 (str): The base58-encoded private key.

    Returns:
        rsa.RSAPrivateKey: The loaded private key.
    """
    try:
        private_key_bytes = base58.b58decode(private_key_base58)
        if len(private_key_bytes) != 32:
            raise ValueError("Unexpected length for the decoded private key bytes.")

        private_key_pem = f"""-----BEGIN PRIVATE KEY-----
{private_key_bytes.hex()}
-----END PRIVATE KEY-----"""

        private_key = serialization.load_pem_private_key(
            private_key_pem.encode(), password=None, backend=default_backend()
        )
        return private_key

    except Exception as e:
        print(f"Error loading private key: {e}")
        return None


def sign_message(private_key, message: bytes) -> bytes:
    """
    Signs a message using the given private key.

    Args:
        private_key: The private key to sign the message with.
        message (bytes): The message to be signed.

    Returns:
        bytes: The signature of the message.
    """
    if private_key is None:
        raise ValueError("Invalid private key provided.")

    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256(),
    )
    return signature


def deserialize_message(
    self, message_type: int, message_data: bytes
) -> message.Message | None:
    """
    Implements the DeserializeMessage method with a random action.

    Args:
        self: The self that is present
        message_type (int): Type of the message to be deserialized.
        message_data (bytes): Data to be deserialized.

    Returns:
        message.Message: The deserialized message.
    """
    msg = None
    try:
        if message_type == ripple_pb2.mtTRANSACTION:
            print("Transaction")
            msg = ripple_pb2.TMTransaction()
            print(f"Message Transaction TMTransaction: {msg}")
        elif message_type == ripple_pb2.mtVALIDATION:
            print("Validation")
            msg = ripple_pb2.TMValidation()
            print(f"Message Validation TMValidation: {msg}")
        elif message_type == ripple_pb2.mtSTATUS_CHANGE:
            print("Status Change")
            msg = ripple_pb2.TMStatusChange()
            print(f"Message Status Change TMStatusChange: {msg}")
        elif message_type == ripple_pb2.mtMANIFESTS:
            print("Manifest")
            msg = ripple_pb2.TMManifests()
            print(f"Message Manifests TMManifests: {msg}")
        elif message_type == ripple_pb2.mtCLUSTER:
            print("Cluster")
            msg = ripple_pb2.TMCluster()
            print(f"Message Cluster TMCluster: {msg}")
        else:
            print("Unknown message type")
    except Exception:
        print(f"Error decoding message: {message_type}")
    return msg
