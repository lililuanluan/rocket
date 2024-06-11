"""This module contains the class that implements a Packet Mutator."""

import random

import base58
from xrpl.core.keypairs.secp256k1 import SECP256K1


class PacketMutator:
    """Class to mutate packets."""

    @staticmethod
    def hex_private_key(private_key: str) -> str:
        """
        encode into hex representation of private key.

        Args:
            private_key: private key of node, the fully encoded bas58 one.

        Returns:
            str: hex representation of private key
        """
        try:
            decoded_priv_key = base58.b58decode(
                private_key, alphabet=base58.XRP_ALPHABET
            )
            priv_key = decoded_priv_key[1:33]
            hex_key = priv_key.hex()

        except Exception as e:
            raise RuntimeError(
                f"Error: Invalid base58 encoded private key: {e}"
            ) from None

        return hex_key

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
                # Neglect mutations for now
                # message.currentTxHash = bytes.fromhex(
                #     "e803e1999369975aed1bfd2444a3552a73383c03a2004cb784ce07e13ebd7d7c"
                # )

                msg_bytes = (
                    b"\x50\x52\x50\x00"
                    + message.proposeSeq.to_bytes(4, "big")
                    + message.closeTime.to_bytes(4, "big")
                    + message.previousledger
                    + message.currentTxHash
                )

                hex_key = self.hex_private_key(private_key_from)
                signature = SECP256K1.sign(msg_bytes, hex_key)
                message.signature = signature
                serialized = message.SerializeToString()

                return serialized
            case _:
                raise ValueError("Message type is not able to be mutated")
