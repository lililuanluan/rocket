"""This module contains the class that implements a Packet Mutator."""

import hashlib
import random

import base58
from ecdsa import util  # type: ignore
from ecdsa.curves import SECP256k1  # type: ignore
from ecdsa.keys import SigningKey  # type: ignore


class PacketMutator:
    """Class to mutate packets."""

    @staticmethod
    def sha512_first_half(message: bytes) -> bytes:
        """
        First half of the bytes of sha512 hash.

        Args:
            message: message from the packet that is mutated

        Returns: sha512 of the mutated message

        """
        sha512 = hashlib.sha512()
        sha512.update(message)
        full_hash = sha512.digest()
        return full_hash[:32]

    @staticmethod
    def sign_message(hash_bytes: bytes, private_key: bytes):
        """
        Sign the message.

        Args:
            hash_bytes: bytes of the hashed message
            private_key: private key of node

        Returns: byte version of key signed
        """
        sk = SigningKey.from_string(private_key, curve=SECP256k1)
        signature = sk.sign_digest(hash_bytes, sigencode=util.sigencode_der)
        return signature

    def base58_private_key(self, private_key: str):
        """
        encode into base58 private key.

        Args:
            private_key: private key of node

        Returns: byte version of key signed
        """
        try:
            priv_key = base58.b58decode(private_key, alphabet=base58.XRP_ALPHABET)
            shortened_priv_key = priv_key[1:33]

        except Exception as e:
            raise RuntimeError(
                f"Error: Invalid base58 encoded private key: {e}"
            ) from None
        return shortened_priv_key

    def mutate_packet(self, message, message_type: int, private_key_from: str):
        """
        Mutates the packet with message type 33.

        Args:
            message: this is the message received, the type is a ripple_pb2.Propose if it is a propose message type
            message_type: type of message, here it is a propose message type 33
            private_key_from: this is the private key of the node

        Returns: Returns the mutated message or raises an error if it is not the right message type
        """
        print("Enter Packet")
        match message_type:
            case 33 if random.random() <= 1:
                message.currentTxHash = bytes.fromhex(
                    "e803e1999369975aed1bfd2444a3552a73383c03a2004cb784ce07e13ebd7d7c"
                )
                print(f"Tx Hash changed with message original: {message}")

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
                shortened_priv_key = self.base58_private_key(private_key_from)
                signature = self.sign_message(hash_bytes, shortened_priv_key)
                print(f"\nSignature: {signature}\n")
                message.signature = signature
                serialized = message.SerializeToString()

                print(f"\nMessage serialised to string: {serialized}\n")

                return serialized
            case _:
                raise ValueError("Message type is not able to be mutated")
