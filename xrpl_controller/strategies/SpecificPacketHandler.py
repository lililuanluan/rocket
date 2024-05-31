import hashlib
import random
import struct
from typing import Tuple, List
from ecdsa import SigningKey, SECP256k1, VerifyingKey
import base58

from xrpl_controller.validator_node_info import ValidatorNode
from protos import ripple_pb2, packet_pb2
from xrpl_controller.strategies.strategy import Strategy

MAX_U32 = 2**32 - 1
validator_node_list_store: List[ValidatorNode] = []
private_key_from = None

class SpecificPacketHandler(Strategy):
    """Class that implements random fuzzer."""

    def __init__(self, send_probability, drop_probability, min_delay_ms, max_delay_ms):
        super().__init__()
        self.send_probability = send_probability
        self.drop_probability = drop_probability
        self.min_delay_ms = min_delay_ms
        self.max_delay_ms = max_delay_ms


    @staticmethod
    def sha512_first_half(message: bytes) -> bytes:
        sha512 = hashlib.sha512()
        sha512.update(message)
        full_hash = sha512.digest()
        return full_hash[:32]

    def get_private_key(self, from_port: int) -> str:

        for node in validator_node_list_store:


            print(f"from port {from_port} peer port: {node.peer.port}")
            if node.peer.port == from_port:
                private_key_from = node.validator_key_data.validation_private_key
                print(f"private key {private_key_from}")
                return private_key_from
        print("Private key not found.")
        return "no private key"


    @staticmethod
    def sign_message(hash_bytes: bytes, private_key: bytes) -> bytes:
        print("before signing")
        signing_key = SigningKey.from_string(private_key, curve=SECP256k1)
        signature = signing_key.sign_digest(hash_bytes)
        print(f"signature: {signature}")
        return signature

    # @staticmethod
    # def verify_signature(message: bytes, signature: bytes, public_key: bytes) -> bool:
    #     verifying_key = VerifyingKey.from_string(public_key, curve=SECP256k1)
    #     hash_message = hashlib.sha512(message).digest()
    #     return verifying_key.verify_digest(signature, hash_message)

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int]:
            print(f"Received packet {packet}")

            length = struct.unpack("!I", packet.data[:4])[0]
            message_type = struct.unpack("!H", packet.data[4:6])[0]
            message_payload = packet.data[6:]
            print(f"length: {length}")
            print(f"Message type {message_type}")

            private_key_from = self.get_private_key(packet.from_port)


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
                print(f"deserealised: {message}")

                if message_type == 33 and random.random() <= 0.15 and private_key_from != "no private key":  # 0.1% chance
                    print("Mutating message...")
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




                    # Decode the private key from base58
                    try:
                        priv_key = base58.b58decode(private_key_from, alphabet=base58.XRP_ALPHABET)
                        actual_priv_key = priv_key[1:33]
                        print(f"Decoded private key: {actual_priv_key}")
                        print(f"Private key length: {len(actual_priv_key)}")
                        if len(actual_priv_key) != 32:
                            raise ValueError("Decoded private key length is incorrect.")
                    except base58.InvalidBase58Error as e:
                        print(f"Base58 decoding error: {e}")
                        raise RuntimeError("Error: Invalid base58 encoded private key")

                    # Sign the message hash
                    signature = self.sign_message(hash_bytes, actual_priv_key)

                    # Verify the signature
                    # pub_key = SigningKey.from_string(actual_priv_key, curve=SECP256k1).verifying_key.to_string()
                    # if not self.verify_signature(hash_bytes, signature, pub_key):
                    #     raise RuntimeError("Error: Signature verification failed")

                    message.signature = signature

                    # Serialize the message
                    message_bytes = message.SerializeToString()
                    print(f"Serialized mutated message: {message_bytes}")

                    changed_packet = struct.pack("!I", length) + struct.pack("!H", message_type) + message_bytes
                    print(f"Changed packet: {changed_packet}")
                    return changed_packet.data, 0

            return packet.data, 0


def getKeys(validator_node_list: List[ValidatorNode]):
    global validator_node_list_store
    validator_node_list_store = validator_node_list
    print(f"Validator list: {validator_node_list_store}")
