import hashlib
import random
import struct
from typing import Tuple, List
from ecdsa import SigningKey, SECP256k1
import base58

from xrpl_controller.validator_node_info import ValidatorNode
from protos import ripple_pb2, packet_pb2
from xrpl_controller.strategies.strategy import Strategy

MAX_U32 = 2**32 - 1
validator_node_list_store: List[ValidatorNode] = []
private_key_from = None


class SpecificPacketHandler(Strategy):
    """Class that implements random fuzzer."""

    def __init__(self, send_probability, drop_probability, min_delay_ms, max_delay_ms, private_key, validator_list):
        """
        Initializes the PacketHandler.

        Args:
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
        self.validator_list = validator_list

    def getKey(self, validator_node_list: List[ValidatorNode]) -> str:
        """
        Gets the private key.

        Args:
            validator_node_list: List of validator nodes.

        Returns:
            str: The private key as a string
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

    @staticmethod
    def sha512_first_half(message: bytes) -> bytes:
        sha512 = hashlib.sha512()
        sha512.update(message)
        full_hash = sha512.digest()
        return full_hash[:32]

    @staticmethod
    def sign_message(hash_bytes: bytes, private_key: bytes) -> bytes:
        hash_message = hashlib.sha512(hash_bytes).digest()
        # Create an ECDSA signing key from the private key
        signing_key = SigningKey.from_string(private_key, curve=SECP256k1)
        # Sign the hashed message
        signature = signing_key.sign(hash_message)
        return signature

    def handle_packet(self, packet: packet_pb2.Packet ) -> Tuple[bytes, int]:
        print(f"PAcket info: {packet.data}")
        print("\n")

        print(f"PAcket fromport: {packet.from_port}")
        print("\n")

        print(f"PAcket to_port: {packet.to_port}")
        print("\n")

        print("\nReceived packet:")
        print(f"{packet}\n")

        length = struct.unpack("!I", packet[:4])[0]
        print(f"Message length: {length}")

        message_type = struct.unpack("!H", packet[4:6])[0]
        print(f"Message type: {message_type}")
        message_payload = packet[6:]
        print(f"Message data: {message_payload}")

        # Define message type mappings
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

        if message_type in message_type_map:
            message_class = message_type_map[message_type]
            message = message_class()
            message.ParseFromString(message_payload)
            print(f"Message type: {message_class}")
            print(f"Deserialized message: {message}")

            if message_type == 33 and random.random() <= -1:  # TMProposeSet
                print("MUTATE !!!!")
                message.currentTxHash = bytes.fromhex("e803e1999369975aed1bfd2444a3552a73383c03a2004cb784ce07e13ebd7d7c")
                print(f"Tx Hash changed with message original: {message}")

                hash_bytes = self.sha512_first_half(
                    b"".join([
                        b"\x50\x52\x50\x00",
                        message.proposeSeq.to_bytes(4, "big"),
                        message.closeTime.to_bytes(4, "big"),
                        message.previousledger,
                        message.currentTxHash,
                    ])
                )

                private_key_from = self.getKey(self.validator_list)

                # Decode the private key from base58
                try:
                    priv_key = base58.b58decode(private_key_from, alphabet=base58.XRP_ALPHABET)
                    actual_priv_key = priv_key[1:33]
                    print(f"Private key with base58: {actual_priv_key}")
                    print(len(actual_priv_key))
                except base58.InvalidBase58Error:
                    print("Error: Invalid base58 encoded private key")
                    raise RuntimeError("Error: Invalid base58 encoded private key")

                # Sign the message hash
                signature = self.sign_message(hash_bytes, actual_priv_key)

                # Set the signature on the message object
                message.signature = signature

                # Serialize the message
                message_bytes = message.SerializeToString()


                print(f"deserialised mutated: {message}")

                changed_packet = struct.pack("!I", length) + struct.pack("!H", message_type) + message_bytes
                print(f"Changed packet: {changed_packet}")
                print("")
                return changed_packet, 0


        else:
            print(f"Unknown message type: {message_type}")

        return packet, 0

            #     def sha512_first_half(message: bytes) -> bytes:
            # sha512 = hashlib.sha512()
            # sha512.update(message)
            # full_hash = sha512.digest()
            # return full_hash[:32]




        #
        # hash = sha512_first_half(bytes_packet_changed)
        #
        # priv_key_bytes = base58.b58decode(self.private_key)
        # priv_key = priv_key_bytes[1:33]
        #
        #
        # sk = SigningKey.from_string(priv_key, curve=SECP256k1)
        #
        # signature = sk.sign_deterministic(hash)
        # print(f"Signature {signature} ")




