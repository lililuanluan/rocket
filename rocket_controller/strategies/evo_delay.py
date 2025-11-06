import random
import struct
from typing import Any, Dict, Tuple
import base58

from protos import packet_pb2, ripple_pb2
from rocket_controller.encoder_decoder import (
    DecodingNotSupportedError,
    PacketEncoderDecoder,
)
from rocket_controller.helper import MAX_U32
from rocket_controller.iteration_type import TimeBasedIteration, LedgerBasedIteration
from rocket_controller.strategies.strategy import Strategy
from xrpl.core.keypairs.secp256k1 import SECP256K1, sha512_first_half

import serialize


class EvoDelayStrategy(Strategy):
    """Class that implements an evolutionary delay-based strategy."""

    def __init__(
        self,
        network_config_path: str = "./config/network/default_network.yaml",
        **kwargs,
    ):
        super().__init__(network_config_path=network_config_path, **kwargs)

        self.delays: list[int] = self.params["encoding"]
        self.byzz_nodes: list[int] = self.network.network_config.get("byzz_nodes", [])

    def setup(self):
        """Setup method for EvoDelayStrategy."""

        # Hardcoded on 7 message types we will consider, could be a parameter in the future
        assert len(self.delays) == 7 * self.network.node_amount * (
            self.network.node_amount - 1
        )

    def get_node_private_key(self, node_id: int) -> str:
        """
        Get the validation private key for a given node ID.

        Args:
            node_id: The ID of the validator node

        Returns:
            The validation private key in base58 format
        """
        if node_id < 0 or node_id >= len(self.network.validator_node_list):
            raise ValueError(f"Invalid node_id: {node_id}")

        return self.network.validator_node_list[
            node_id
        ].validator_key_data.validation_private_key

    def sign_validation_message(
        self, validation_dict: Dict[str, Any], private_key: str
    ) -> bytes:
        """
        Sign a validation message and return the signature.

        Args:
            validation_dict: The validation message as a dictionary (without Signature field)
            private_key: The validation private key in base58 format

        Returns:
            The signature as bytes
        """
        # Remove Signature field if present
        validation_for_signing = {
            k: v for k, v in validation_dict.items() if k != "Signature"
        }

        # Serialize the validation data without signature
        serialized_data = self.parse_validation_content(validation_for_signing)

        # Create the data to sign: "VAL\0" prefix + serialized validation
        bytes_to_sign = b"VAL\x00" + serialized_data

        # Compute SHA512 first half
        hash_to_sign = sha512_first_half(bytes_to_sign)

        # Decode the base58 private key to hex format for signing
        # Extract bytes 1:33 (32 bytes) from the decoded key, matching network_manager.py
        decoded_key = base58.b58decode(private_key, alphabet=base58.RIPPLE_ALPHABET)[
            1:33
        ]
        private_key_hex = decoded_key.hex()

        # Sign the hash
        signature = SECP256K1.sign(hash_to_sign, private_key_hex)

        return signature

    def _ensure_hex_strings(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert bytes fields to hex strings for JSON serialization.

        Args:
            data: Dictionary that may contain bytes values

        Returns:
            Dictionary with bytes converted to hex strings
        """
        result = {}
        for key, value in data.items():
            if isinstance(value, bytes):
                result[key] = value.hex()
            else:
                result[key] = value
        return result

    def modify_validation_message(
        self,
        message,
        modifications: Dict[str, Any],
        node_id: int = None,
        private_key: str = None,
    ) -> bytes:
        """
        Modify a validation message and return the modified packet data.

        Args:
            message: The TMValidation protobuf message
            modifications: Dictionary of fields to modify (e.g., {'LedgerSequence': 4})
            node_id: The node ID to get the private key from (if private_key not provided)
            private_key: The validation private key in base58 format (if not provided, uses node_id)

        Returns:
            Modified packet data as bytes
        """
        if not SERIALIZE_AVAILABLE:
            raise RuntimeError("serialize module not available")

        # Parse the original validation content
        parsed = self.parse_validation_content(message)

        if "error" in parsed:
            raise ValueError(f"Cannot parse validation: {parsed['error']}")

        # Apply modifications
        for key, value in modifications.items():
            parsed[key] = value

        # Get private key if not provided
        if private_key is None:
            if node_id is None:
                raise ValueError("Either node_id or private_key must be provided")
            private_key = self.get_node_private_key(node_id)

        # Sign the modified validation message
        signature = self.sign_validation_message(parsed, private_key)

        # Add the signature to the parsed data (as hex string for JSON serialization)
        parsed["Signature"] = signature.hex()

        # Ensure all bytes fields are hex strings for JSON serialization
        parsed = self._ensure_hex_strings(parsed)

        # Serialize back to bytes
        modified_validation_bytes = self.parse_validation_content(parsed)

        # Create a new TMValidation message with modified data

        new_message = ripple_pb2.TMValidation()
        new_message.CopyFrom(message)
        new_message.validation = modified_validation_bytes

        # Re-encode to packet data
        new_packet_data = PacketEncoderDecoder.encode_message(new_message, 41)

        return new_packet_data

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int, int]:
        """
        Implements the handle_packet method with an encoding of delays.

        Args:
            packet: The original packet to be sent.

        Returns:
            Tuple[bytes, int, int]: The new packet, the delay and the send amount.
        """

        # Code taken from packet decoder
        message, message_type = PacketEncoderDecoder.decode_packet(packet)

        if message_type not in set(range(30, 36)).union({41}):
            return packet.data, 0, 1

        # Types used in evolutionary paper: https://doi.org/10.1109/ICSE-SEIP58684.2023.00009
        # 30: ripple_pb2.TMTransaction
        # 31: ripple_pb2.TMGetLedger
        # 32: ripple_pb2.TMLedgerData
        # 33: ripple_pb2.TMProposeSet
        # 34: ripple_pb2.TMStatusChange
        # 35: ripple_pb2.TMHaveTransactionSet
        # 41: ripple_pb2.TMValidation

        # To get type index -> subtract 30, for validation, subtract 35
        type_id = message_type - 30 if message_type != 41 else 6
        sender_node_id = self.network.port_to_id(packet.from_port)
        receiver_node_id = self.network.port_to_id(packet.to_port)

        # for n nodes
        # index = num(message_type) * (n * n-1)
        #           + from_id * (n-1)
        #           + conditional(to_id)
        # conditional(to_id) -> if to_id is larger than from_id, return to_id-1, else return to_id.

        index = (
            type_id * (self.network.node_amount * (self.network.node_amount - 1))
            + sender_node_id * (self.network.node_amount - 1)
            + (
                receiver_node_id
                if receiver_node_id < sender_node_id
                else receiver_node_id - 1
            )
        )

        # Byzantine节点修改validation消息
        if message_type == 41 and SERIALIZE_AVAILABLE:
            try:
                # 1. 解析原始validation消息
                parsed = self.parse_validation_content(message)
                print(f"Original validation: {parsed}")
                original_seq = parsed.get("LedgerSequence", 0)


                # 2. 修改validation并重新签名
                # 方式1: 使用modify_validation_message（推荐，一步完成）
                modified_packet_data = self.modify_validation_message(
                    message,
                    modifications={
                        "LedgerSequence": original_seq + 1
                    },
                    node_id=sender_node_id,  # 使用发送节点的私钥签名
                )


                print(
                    f"Packet re-signed and serialized ({len(modified_packet_data)} bytes)"
                )

                # 解码修改后的packet以验证
                # 从bytes创建临时Packet对象
                temp_packet = packet_pb2.Packet()
                temp_packet.data = modified_packet_data
                modified_message, _ = PacketEncoderDecoder.decode_packet(temp_packet)
                parsed_modified = self.parse_validation_content(modified_message)
                print(
                    f"modified validation: {parsed_modified}"
                )

            except Exception as e:
                print(
                    f"[Byzantine Node {sender_node_id}] Error modifying validation: {e}"
                )

        # Get index through a default function
        # Return with delay=self.delays[index]

        return packet.data, self.delays[index], 1
