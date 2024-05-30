"""This module contains the class that implements a random fuzzer."""
import hashlib
import struct
import random
from typing import Tuple
from typing import List
from ecdsa import SigningKey, SECP256k1

import base58
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from google.protobuf import message

from xrpl_controller.validator_node_info import ValidatorNode


from protos import packet_pb2
from xrpl_controller.strategies.strategy import Strategy


MAX_U32 = 2**32 - 1
validator_node_list_store: List[ValidatorNode] = []
private_key_from = None


class PacketHandler(Strategy):
    """Class that implements random fuzzer."""

    def __init__(self, send_probability, drop_probability, min_delay_ms, max_delay_ms, private_key, validator_list):
        """
        Implements the intilisation of PacketHandler.

        Args:
            self
            send_probability (float): Probability of sending the packet
            drop_probability (float): Probability of dropping the packet
            min_delay_ms (float): Minimum delay in milliseconds
            max_delay_ms (float): Maximum delay in milliseconds.

        """
        self.send_probability = send_probability
        self.drop_probability = drop_probability
        self.min_delay_ms = min_delay_ms
        self.max_delay_ms = max_delay_ms
        self.private_key = None
        self.validator_list = None

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

    def handle_packet(self, packet: bytes) -> Tuple[bytes, int]:
        """
        Implements the handle_packet method with a random action.

        Args:
            packet: the original packet to be sent.

        Returns:
        Tuple[bytes, int]: the new packet and the random action.
        """
        print("\n")
        print(f"Received packet: {packet}")

        print("\n")
        length = struct.unpack("!I", packet[:4])[0]
        print(f"Message length: {length}")

        message_type = struct.unpack("!H", packet[4:6])[0]
        print(f"Message type: {message_type}")
        message_payload = packet[6:]
        print(f"Message data: {message_payload}")

        # Define message type mappings
        message_type_map = {
            2: packet_pb2.TMManifests,
            3: packet_pb2.TMPing,
            5: packet_pb2.TMCluster,
            15: packet_pb2.TMEndpoints,
            30: packet_pb2.TMTransaction,
            31: packet_pb2.TMGetLedger,
            32: packet_pb2.TMLedgerData,
            33: packet_pb2.TMProposeSet,
            34: packet_pb2.TMStatusChange,
            35: packet_pb2.TMHaveTransactionSet,
            41: packet_pb2.TMValidation,
            42: packet_pb2.TMGetObjectByHash,
        }

        # Define reverse lookup for message type names
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
            print("\n")
            print(f"Message type: {message_class}")
            print(f"Deserialized message: {message}")

            if message_type == 33:  # TMGetLedger
                message.currentTxHash = bytes.fromhex("e803e1999369975aed1bfd2444a3552a73383c03a2004cb784ce07e13ebd7d7c")
                print(f"Tx Hash changed with message original: {message}")


                def sha512_first_half(data: bytes) -> bytes:
                    hash_bytes = hashlib.sha512(data).digest()
                    return hash_bytes[:32]

                def sign_message(hash_bytes: bytes, private_key: bytes) -> bytes:
                    algo = SECP256k1.lib.secp256k1_context_create(SECP256k1.ALL_FLAGS)
                    priv_key = SECP256k1.PrivateKey(private_key, raw=True)
                    message = SECP256k1.lib.secp256k1_ecdsa_signature_parse_der(
                        algo, hash_bytes, len(hash_bytes)
                    )
                    signature = priv_key.ecdsa_sign(hash_bytes, raw=True)
                    signature_der = SECP256k1.lib.secp256k1_ecdsa_signature_serialize_der(
                        algo, signature, None, 0
                    )
                    SECP256k1.lib.secp256k1_context_destroy(algo)
                    return bytes(signature_der)

                hash_bytes = sha512_first_half(
                    b"".join([
                        b"\x50\x52\x50\x00",
                        message.closeTime.to_bytes(4, "big"),
                        message.previousledger,
                        message.currentTxHash,
                    ])
                )

                priv_key = base58.b58decode(self.private_key)
                signature = sign_message(hash_bytes, priv_key[1:33])



                # Create an ECDSA signing key from the private key


                message.signature = signature
                message_bytes = message.SerializeToString()

                print(f"Message bytes: {message_bytes}")
                print(f"Signature final: {signature}")
        else:
            print(f"Unknown message type: {message_type}")

        return packet,0


        #     modified_packet = (
        #             struct.pack("!I", length)
        #             + struct.pack("!H", message_type)
        #             + modified_payload
        #     )
        #
        #     print(f"Modified packet: {modified_packet}")
        #     print("\n")
        #
        #     modified_length = struct.unpack("!I", modified_packet[:4])[0]
        #     print(f"Changed Message length: {modified_length}")
        #
        #     modified_message_type = struct.unpack("!H", modified_packet[4:6])[0]
        #     print(f"Changed Message type: {modified_message_type}")
        #     print("\n")
        #     modified_message_payload = modified_packet[6:]
        #     print(f"Changed Message data: {modified_message_payload}")
        #
        #     if modified_message_type in message_type_map:
        #         message_class = message_type_map[modified_message_type]
        #
        #         message = message_class()
        #         message.ParseFromString(modified_message_payload)
        #         print("\n")
        #         print(f" same Message type: {message_class}")
        #         print(f" changed Deserialized message: {message}")
        #         print("\n")
        #
        #         if(modified_message_payload == message_payload):
        #
        #             print(f"They are the same")
        #         else:
        #             print(f"They are different")
        #
        #         if(modified_payload == message_payload):
        #             print(f"They are the same2")
        #         else:
        #             print(f"They are different2")
        #         if(modified_payload == modified_message_payload):
        #             print(f"They are the same3")
        #         else:
        #             print(f"They are different3")
        #
        #         print("\n")
        #
        #
        #
        #
        # else:
        #     print(f"Unknown message type: {message_type}")
        #     modified_packet = packet
        #
        # # Example of modifying binary data
        #
        # modified_message_payload = modified_packet[6:]
        #
        #
        #
        #
        #
        #
        #
        # binary_data = bytearray(modified_message_payload)
        # original_data = binary_data
        # print(f"This is the original bytes with arbitary parts for type 31: {binary_data}")
        # print(f"This is the orig length {len(binary_data)}")
        # print("\n")
        # data_length = len(binary_data)
        # changes = 10
        #
        # for _ in range(changes):
        #     # Select a random index within the packet
        #     index = random.randint(0, data_length - 1)
        #
        #     # Apply an arbitrary modification (e.g., XOR with a random value)
        #     binary_data[index] ^= 0xFF
        #
        #
        #
        #
        #
        # print(
        #     f"This is the modified bytes with arbitary parts for type 31: {binary_data}"
        # )
        # print(f"This is the modified length {len(binary_data)}")
        # print("\n")
        #
        # bytes_packet_changed = (
        #         struct.pack("!I", length)
        #         + struct.pack("!H", message_type)
        #         + bytes(binary_data)
        # )
        #
        # print(f"Modified bytes packet: {bytes_packet_changed}")
        # print("\n")
        #
        #
        # def sha512_first_half(message: bytes) -> bytes:
        #     sha512 = hashlib.sha512()
        #     sha512.update(message)
        #     full_hash = sha512.digest()
        #     return full_hash[:32]
        #
        #
        # hash = sha512_first_half(bytes_packet_changed)
        #
        # priv_key_bytes = base58.b58decode(self.private_key)
        # priv_key = priv_key_bytes[1:33]
        #
        #

        #
        # signature = sk.sign_deterministic(hash)
        # print(f"Signature {signature} ")
        #
        #
        # # bytes_packet_changed.set_signature(signature)
        #
        #
        #
        #
        #
        # modified_bytes_length = struct.unpack("!I", bytes_packet_changed[:4])[0]
        # print(f"Changed Message length of bytes: {modified_bytes_length}")
        # print(f"Modified bytes length: {len(bytes_packet_changed)}")
        #
        # bytes_message_type = struct.unpack("!H", modified_packet[4:6])[0]
        # print(f"Changed Message bytes type: {bytes_message_type}")
        # print("\n")
        # bytes_message_payload = modified_packet[6:]
        # print(f"Changed Message bytes data: {bytes_message_payload}")
        #
        # if bytes_message_type in message_type_map:
        #     message_class = message_type_map[bytes_message_type]
        #
        #     message = message_class()
        #     message.ParseFromString(modified_message_payload)
        #     print("\n")
        #     print(f" same bytes Message type: {message_class}")
        #     print(f" changed bytes Deserialized message: {message}")
        #     print("\n")
        #


            #
            # return bytes_packet_changed,0









        #
        # message_json = json.dumps(modified_packet, default=str).encode('utf-8')
        #
        #
        #
        # validator_node_list = self.validator_list  # Replace this with how you obtain the list
        # private_key_from = self.getKey(validator_node_list)
        # print(f"Private key: {private_key_from}")
        #
        # try:
        #     private_key = load_private_key_from_base58(private_key_from)
        #     print(f"Private key Loaded: {private_key}")
        # except ValueError as e:
        #     print(f"Error loading private key: {e}")
        #
        #
        #
        # # Sign the modified packet with the private key
        #
        # try:
        #     signature = private_key.sign(
        #         message_json,
        #         padding.PSS(
        #             mgf=padding.MGF1(hashes.SHA256()),
        #             salt_length=padding.PSS.MAX_LENGTH
        #         ),
        #         hashes.SHA256()
        #     )
        #     modified_packet_with_signature = modified_packet + signature
        #     print(f"This is the packet with signature modified with arbitrary parts, binary data for type 31: {modified_packet_with_signature}")
        #     print(f"This is the original packet {packet}")
        #     return bytes(packet), 0
        # except Exception as e:
        #     print(f"Exception: {e}")









        #  ripple_message = self.deserialize_message(message_type, message_payload)


def load_private_key_from_base58(private_key_base58: str) -> rsa.RSAPrivateKey:
    try:
        # Decode the Base58 string to bytes
        private_key_bytes = base58.b58decode(private_key_base58)

        # Check the length of the decoded bytes
        if len(private_key_bytes) != 32:
            raise ValueError("Unexpected length for the decoded private key bytes.")

        # Create a PEM-formatted key (assuming raw key bytes)
        private_key_pem = f"""-----BEGIN PRIVATE KEY-----
{private_key_bytes.hex()}
-----END PRIVATE KEY-----"""

        # Attempt to load the private key
        private_key = serialization.load_pem_private_key(
            private_key_pem.encode(),
            password=None,
            backend=default_backend()
        )
        return private_key

    except Exception as e:
        print(f"Error loading private key: {e}")
        return None


def sign_message(private_key, message: bytes) -> bytes:
    if private_key is None:
        raise ValueError("Invalid private key provided.")

    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return signature



def deserialize_message(
        self, message_type: int, message_data: bytes
    ) -> message.Message:
        """
        Implements the DeserializeMessage method with a random action.

        Args:
            self
            message_type: Type of the message to be deserialized.
            message_data: Data to be deserialized.

        Returns:
        Message: The deserialized message.
        """
        try:
            if message_type == packet_pb2.mtTRANSACTION:
                print("Transaction")
                msg = packet_pb2.TMTransaction()
                print(f"Message Transaction mTransaction: {msg}")
            elif message_type == packet_pb2.mtVALIDATION:
                print("Validation")
                msg = packet_pb2.TMValidation
                print(f"Message Transaction TMValidation: {msg}")
                # Add other message types as needed
            elif message_type == packet_pb2.mtSTATUS_CHANGE:
                print("status")
                msg = packet_pb2.TMStatusChange()
                print(f"Message Status Change TMStatusChange: {msg}")
            elif message_type == packet_pb2.mtMANIFESTS:
                print("Manifest")
                msg = packet_pb2.TMManifests()
                print(f"Message Manifests TMManifests: {msg}")
            elif message_type == packet_pb2.mtCLUSTER:
                print("Cluster")
                msg = packet_pb2.TMCluster()
                print(f"Message Cluster TMCluster: {msg}")
            elif message_type == packet_pb2.mtENDPOINTS:
                print("endpoints")
                msg = packet_pb2.TMEndpoints()
                print(f"Message Endpoints TMEndpoints: {msg}")
            elif message_type == packet_pb2.mtPEER_SHARD_INFO:
                print("peer")
                msg = packet_pb2.TMPeerShardInfo()
                print(f"Message Peer Shard Info TMPeerShardInfo: {msg}")
            elif message_type == packet_pb2.mtPROPOSE_LEDGER:
                print("proposeLEdger")
                msg = packet_pb2.TMProposeLedger()
                print(f"Message Propose Set TMProposeSet: {msg}")
            else:
                print(f"Unknown Message Type: {message_type}")
                return None
        except Exception as e:
            print(f"Failed to deserialize message: {e}")
            return None

        msg.ParseFromString(message_data)

        return msg
