"""This module contains the class that implements a random fuzzer."""

import struct
from typing import Tuple
from typing import List
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

    def __init__(self, send_probability, drop_probability, min_delay_ms, max_delay_ms):
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

    def getKey(self, validator_node_list: List[ValidatorNode]) -> str:
        """
        Implements a method to get the private key.

        Args:
            validator_node_list: List[ValidatorNode] List of validator nodes.

        Returns:
            str: this is the string of the private key

        """
        validator_node_list_store = validator_node_list

        print(f"Stored validator info: {validator_node_list_store}")

        for node in validator_node_list_store:
            print(f"Stored validator: {node}")
            if node.ws_public.port == 6100:
                private_key = node.validator_key_data.validation_private_key
                private_key_from = private_key
                print(f"Private key: {private_key}")
                return private_key
            private_key = "no_key"

        return private_key

    def handle_packet(self, packet: bytes) -> Tuple[bytes, int]:
        """
        Implements the handle_packet method with a random action.

        Args:
            packet: the original packet to be sent.

        Returns:
        Tuple[bytes, int]: the new packet and the random action.
        """
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
            print(f"Message type: {message_class}")
            print(f"Deserialized message: {message}")

            if message_type == 31:  # TMGetLedger
                message.ledgerSeq = 123456
                print(f"Ledger seq: {message.ledgerSeq}")

            modified_payload = message.SerializeToString()
            modified_packet = (
                struct.pack("!I", length)
                + struct.pack("!H", message_type)
                + modified_payload
            )

        else:
            print(f"Unknown message type: {message_type}")
            modified_packet = packet

        # Example of modifying binary data

        binary_data = bytearray(modified_packet)
        print(
            f"This is the original bytes with arbitary parts for type 31: {binary_data}"
        )
        binary_data[1] ^= 0xFF  # Example: XOR byte at index 10 with 0xFF
        print(
            f"This is the modified bytes with arbitary parts for type 31: {binary_data}"
        )

        # signature = self.getKey(validator_node_list_store).sign(bytes(binary_data),
        #                                             padding.PSS(
        #                                                 mgf=padding.MGF1(hashes.SHA256()),
        #                                                 salt_length=padding.PSS.MAX_LENGTH
        #                                             ),
        #                                             hashes.SHA256()
        #                                             )
        #
        # modified_packet_with_signature = modified_packet + signature
        # print(f"This is the Packet with signature modified with arbitary parts, binary date for type 31: {modified_packet_with_signature}")
        # print(f"This is the original packet {packet}")
        # return bytes(modified_packet_with_signature), 0
        return bytes(packet), 0

        #  ripple_message = self.deserialize_message(message_type, message_payload)

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
