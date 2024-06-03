
import hashlib
import random
from typing import List
from ecdsa import SigningKey, SECP256k1
import base58

from xrpl_controller.validator_node_info import ValidatorNode

MAX_U32 = 2 ** 32 - 1
validator_node_list_store: List[ValidatorNode] = []


class PacketMutator:
    """Class to mutate packets."""

    @staticmethod
    def sha512_first_half(message: bytes) -> bytes:
        """
        sha512 on first half of all bytes
        Args:
            message: message from the packet that is mutated

        Returns: sha512 of the mutated message
        """
        sha512 = hashlib.sha512()
        sha512.update(message)
        full_hash = sha512.digest()
        return full_hash[:32]

    @staticmethod
    def sign_message(hash_bytes: bytes, private_key: bytes) -> bytes:
        """
        Sign the message.
        Args:
            hash_bytes: bytes of the hashed message
            private_key: private key of node

        Returns: byte version of key signed
        """
        signing_key = SigningKey.from_string(private_key, curve=SECP256k1)
        return signing_key.sign_digest(hash_bytes)

    def mutate_packet(self, message, message_type, private_key_from):
        """
        Mutates the packet with message type 33.
        Args:
            message: this is the message received
            message_type: type of message, here it is a propose message type 33
            private_key_from: this is the private key of the node

        Returns: Returns the mutated message or raises an error if it is not the right message type
        """
        print("Enter Packet")
        if message_type == 33 and random.random() <= 0.05 and private_key_from != "no private key":
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

            try:
                priv_key = base58.b58decode(private_key_from, alphabet=base58.XRP_ALPHABET)
                actual_priv_key = priv_key[1:33]
                if len(actual_priv_key) != 32:
                    raise ValueError("Decoded private key length is incorrect.")
            except base58.InvalidBase58Error:
                raise RuntimeError("Error: Invalid base58 encoded private key") from None

            signature = self.sign_message(hash_bytes, actual_priv_key)
            print(f"\nSignature: {signature}")
            message.signature = signature
            serialized = message.SerializeToString()

            print(f"\nMessage serialised to string: {serialized}")

            return serialized
        raise ValueError("Message type is not able to be mutated")