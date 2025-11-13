import random
import struct
from typing import Any, Dict, Tuple
import base58

from protos import packet_pb2, ripple_pb2
from rocket_controller.encoder_decoder import (
    DecodingNotSupportedError,
    PacketEncoderDecoder,
    ValidationDict,
)
from rocket_controller.helper import MAX_U32
from rocket_controller.iteration_type import TimeBasedIteration, LedgerBasedIteration
from rocket_controller.strategies.strategy import Strategy
from xrpl.core.keypairs.secp256k1 import SECP256K1, sha512_first_half

import serialize
import re
from pathlib import Path

TMP_ERROR_FILE = Path(__file__).parent / "../../evo/out/error.log" # TODO add this as a param


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

        print(f"dumping errors to {TMP_ERROR_FILE}")

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
    ) -> ValidationDict:
        """
        Parse a validation message, apply in-place modifications, and return
        the parsed ValidationDict. Signing and serialization are left to
        `PacketEncoderDecoder.sign_message(parsed, private_key)`.

        Args:
            message: The TMValidation protobuf message
            modifications: Dictionary of fields to modify (e.g., {'LedgerSequence': 4})

        Returns:
            ValidationDict: The modified parsed validation dictionary.
        """

        # Parse the original validation content
        parsed = self.parse_validation_content(message)

        if isinstance(parsed, dict) and parsed.get("error"):
            raise ValueError(f"Cannot parse validation: {parsed['error']}")

        # Apply modifications in-place
        for key, value in modifications.items():
            parsed[key] = value

        return parsed

    def parse_validation_content(self, validation_message) :
        return PacketEncoderDecoder.decode_validation(validation_message)

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
        
        self.test_sign_message(packet)

        # Byzantine节点修改validation消息
        # if message_type == 41:
        #     try:
        #         # 1. 解析原始validation消息
        #         parsed = self.parse_validation_content(message)
        #         # print(f"Original validation: {parsed}")
        #         original_seq = parsed.get("LedgerSequence", 0)

        #         # 2. 修改validation并重新签名
        #         # 方式1: 使用modify_validation_message（推荐，一步完成）
        #         modified_packet = self.modify_validation_message(
        #             message,
        #             modifications={"LedgerSequence": original_seq + 1},
        #             node_id=sender_node_id,  # 使用发送节点的私钥签名
        #         )

        #         print(
        #             f"Packet re-signed and serialized ({len(modified_packet.data)} bytes)"
        #         )

        #         # 解码修改后的packet以验证
        #         # 从bytes创建临时Packet对象

        #         modified_message, _ = PacketEncoderDecoder.decode_packet(
        #             modified_packet
        #         )
        #         parsed_modified = self.parse_validation_content(modified_message)
        #         print(f"modified validation: {parsed_modified}")

        #     except Exception as e:
        #         print(
        #             f"[Byzantine Node {sender_node_id}] Error modifying validation: {e}"
        #         )

        # Get index through a default function
        # Return with delay=self.delays[index]

        return packet.data, self.delays[index], 1
    
    def test_sign_message(self, packet: packet_pb2.Packet):
        message, message_type = PacketEncoderDecoder.decode_packet(packet)
        sender_node_id = self.network.port_to_id(packet.from_port)
        
        message_class = PacketEncoderDecoder.message_type_map[message_type]
        message_copy = message_class()
        if message_type in [33, 41]:  # TMProposeSet or TMValidation    
            message_copy.CopyFrom(message) 
        
        if message_type == 33:  # TMProposeSet
            signed_message = PacketEncoderDecoder.sign_message(
                message_copy,
                self.network.public_to_private_key_map[message.nodePubKey.hex()],
            )
            if signed_message.signature.hex() != message.signature.hex():
                # 将不匹配写入tmp文件
                with open(TMP_ERROR_FILE, "a") as f:
                    f.write(
                        f"Signature mismatch for node {sender_node_id} proposeSeq {message.proposeSeq}\n"
                    )
                    
        if message_type == 41:
            parsed = self.parse_validation_content(message)

            # Prefer to lookup the private key via the SigningPubKey extracted
            # from the parsed validation (this mirrors how ProposeSet uses
            # message.nodePubKey). Fall back to node_id-based lookup if the
            # public key is missing or not mapped.
            # TODO: fix this sh**t
            def _normalize_pubhex(val: Any) -> str:
                if not val:
                    return ""
                if isinstance(val, bytes):
                    return val.hex()
                if isinstance(val, str):
                    s = val
                    if (s.startswith("b'") and s.endswith("'")) or (
                        s.startswith('b"') and s.endswith('"')
                    ):
                        s = s[2:-1]
                    if s.startswith("0x") or s.startswith("0X"):
                        s = s[2:]
                    s_sanitized = re.sub(r'[^0-9A-Fa-f]', '', s)
                    return s_sanitized.lower()
                return str(val).lower()

            signing_pub = parsed.get("SigningPubKey", "") if isinstance(parsed, dict) else ""
            signing_pub_hex = _normalize_pubhex(signing_pub)

            private_key_candidate = None
            if signing_pub_hex:
                # lookup map keys are stored as lowercase hex
                private_key_candidate = self.network.public_to_private_key_map.get(signing_pub_hex)

            # IMPORTANT: do NOT fallback to sender node_id — this is a gossip network
            # and the authoritative private key for a validation must be looked up
            # from the message's SigningPubKey. If the mapping is missing, skip
            # signing/verification checks for this packet and log the issue.
            if not private_key_candidate:
                msg = (
                    f"Missing private key mapping for SigningPubKey {signing_pub_hex} (node {sender_node_id}). Skipping validation signing checks."
                )
                print(msg)
                with open(TMP_ERROR_FILE, "a") as f:
                    f.write(msg + "\n")
                # skip further checks for this packet
                return

            # map stores decoded private key as hex (see NetworkManager)
            private_key_for_signing = private_key_candidate

            # PacketEncoderDecoder.sign_message now accepts a parsed
            # ValidationDict and returns a signed TMValidation.
            signed_message = PacketEncoderDecoder.sign_message(
                parsed,
                private_key_for_signing,
            )

            parsed_signed = self.parse_validation_content(signed_message)
            # If parsing failed for either original or signed message, log that
            if isinstance(parsed, dict) and parsed.get("error"):
                print(f"[parse error] original validation parse failed: {parsed.get('error')}")
            if isinstance(parsed_signed, dict) and parsed_signed.get("error"):
                print(f"[parse error] signed validation parse failed: {parsed_signed.get('error')}")

            orig_sig = parsed.get("Signature", "") if isinstance(parsed, dict) else ""
            new_sig = parsed_signed.get("Signature", "") if isinstance(parsed_signed, dict) else ""

            if new_sig != orig_sig:
                # Rebuild canonical signing payload once and run compact diagnostics.
                try:
                    signing_dict = {k: v for k, v in parsed.items() if k != "Signature"}
                    payload = bytes(serialize.serialize_bytes(signing_dict))
                    bytes_to_sign = b"VAL\x00" + payload
                except Exception as e:
                    raise RuntimeError(f"Failed to rebuild signing payload: {e}")

                def _hex_to_bytes_loose(s: str) -> bytes:
                    if not s:
                        return b""
                    ss = s
                    if (ss.startswith("b'") and ss.endswith("'")) or (ss.startswith('b"') and ss.endswith('"')):
                        ss = ss[2:-1]
                    if ss.startswith("0x") or ss.startswith("0X"):
                        ss = ss[2:]
                    ss = re.sub(r'[^0-9A-Fa-f]', '', ss)
                    if len(ss) % 2 == 1:
                        ss = '0' + ss
                    try:
                        return bytes.fromhex(ss)
                    except Exception:
                        return b""

                orig_sig_b = _hex_to_bytes_loose(orig_sig)
                new_sig_b = _hex_to_bytes_loose(new_sig)
                signing_pub = parsed.get("SigningPubKey", "")

                valid_orig = bool(orig_sig_b and bytes_to_sign and signing_pub and SECP256K1.is_valid_message(bytes_to_sign, orig_sig_b, signing_pub))
                valid_new = bool(new_sig_b and bytes_to_sign and signing_pub and SECP256K1.is_valid_message(bytes_to_sign, new_sig_b, signing_pub))

                priv_fingerprint = ""
                pub_hex = ""
                pub_match = False
                try:
                    priv_hex = private_key_for_signing
                    priv_fingerprint = f"{priv_hex[:8]}..{priv_hex[-8:]}"
                    # derive compressed public key
                    from ecpy.keys import ECPrivateKey
                    from ecpy.curves import Curve

                    curve = Curve.get_curve("secp256k1")
                    priv_int = int(priv_hex, 16)
                    wrapped_priv = ECPrivateKey(priv_int, curve)
                    pub_point = wrapped_priv.get_public_key()
                    pub_bytes = bytes(curve.encode_point(pub_point.W, compressed=True))
                    pub_hex = pub_bytes.hex()
                    signing_pub_norm = re.sub(r'[^0-9A-Fa-f]', '', str(signing_pub or ''))
                    pub_match = (signing_pub_norm.lower() == pub_hex.lower())
                except Exception:
                    pass

                msg = (
                    f"Signature mismatch node={sender_node_id} ledger={parsed.get('LedgerSequence','N/A')} "
                    f"orig_ok={valid_orig} new_ok={valid_new} priv_fp={priv_fingerprint} pub_match={pub_match} payload_hex={bytes_to_sign[:32].hex()}.."
                )
                print(msg)
                with open(TMP_ERROR_FILE, "a") as f:
                    f.write(msg + "\n")
            else:
                print(f"validation signature SUCCESS for node {sender_node_id} ledgerSeq {parsed.get('LedgerSequence', 'N/A')}")
