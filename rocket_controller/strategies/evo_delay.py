from email import message
import random
import struct
from typing import Any, Dict, Tuple
from functools import singledispatchmethod
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
from loguru import logger

TMP_ERROR_FILE = Path(__file__).parent / "../../evo/out/error.log" # TODO add this as a param


def _normalize_pubhex(val: Any) -> str:
    """Normalize a SigningPubKey-like value to lowercase hex string.

    Handles bytes, hex strings (with optional 0x prefix), and strings that
    may be wrapped like "b'...'." Returns empty string for falsy inputs.
    This central helper prevents duplicated logic across the module.
    """
    if not val:
        return ""
    if isinstance(val, (bytes, bytearray)):
        return bytes(val).hex()
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

        self.dummy_proposal = bytes.fromhex(
            "e803e1999369975aed1bfd2444a3552a73383c03a2004cb784ce07e13ebd7d7c"
        )
        self.dummy_validation = "E803E1999369975AED1BFD2444A3552A73383C03A2004CB784CE07E13EBD7D7C"
        # seq -> set of proposals
        self.old_proposals = {-1: set([self.dummy_proposal,])}
        # seq -> set of validations
        self.old_validation_hashes = {-1: set([self.dummy_validation,])}
        self.byzz_mutate_methods = (
            {  # TODO: add mutation for TMGetLedger and TMLedgerData
                ripple_pb2.TMProposeSet: [
                    "do_nothing",
                    "replace_tx_hash",
                    "increment_propose_seq",
                    "repeat_5",
                ],
                ripple_pb2.TMValidation: [
                    "do_nothing",
                    "replace_ledger_hash",
                    "replace_ledger_hash_with_dummy",
                    "increment_ledger_sequence",
                    "repeat_5",
                ],
            }
        )

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

    def parse_validation_content(self, validation_message) :
        return PacketEncoderDecoder.decode_validation(validation_message)

    # 拜占庭行为（byzzfuzz）：
    # transaction消息：更改交易的amount
    # proposeset：更改txs hash或者sequence number
    # validation：更改id（pubkey？）或者sequence number
    # 分为small scope和any scope
    # small scope：对数值+1，对hash替换为网络中的前一个hash

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

        # possibly mutate
        if (
            3
            <= self.iteration_type.get_ledger_sequence_cur_max()
            <= self.max_ledger_seq - 5
        ):
            if isinstance(message, ripple_pb2.TMProposeSet):
                # cache old proposals
                prop_seq = message.proposeSeq
                if prop_seq not in self.old_proposals:
                    self.old_proposals[prop_seq] = set()
                self.old_proposals[prop_seq].add(message.currentTxHash)
                # identify original sender
                _pub_key = message.nodePubKey.hex()
                original_sender = self.pubkey_to_node_id(_pub_key)
                if original_sender not in self.byzz_nodes:
                    # only mutate if sender is byzz node
                    return packet.data, self.delays[index], 1

                # logger.debug(
                #     f"Mutating propose from non-byzz node {original_sender}, sender_node_id={sender_node_id}"
                # )
                # message sent by byzz nodes:
                method = random.choice(
                    self.byzz_mutate_methods[ripple_pb2.TMProposeSet]
                )
                is_mutated = False
                if method == "do_nothing":
                    # logger.debug("Byzz mutate method: do_nothing")
                    pass
                elif method == "replace_tx_hash":
                    # logger.debug("Byzz mutate method: replace_tx_hash")
                    message = self._replace_txs_with_old_propose(message)
                    is_mutated = True
                elif method == "increment_propose_seq":
                    # logger.debug("Byzz mutate method: increment_propose_seq")
                    message = self._increment_propose_seq(message)
                    is_mutated = True
                elif method == "repeat_5":
                    return packet.data, self.delays[index], 5
                if is_mutated:
                    # logger.debug(f"Signing mutated propose from node {original_sender}")
                    signed_message = PacketEncoderDecoder.sign_message(
                        message,
                        self.network.public_to_private_key_map[_pub_key],
                    )
                else:
                    signed_message = message

                encoded = PacketEncoderDecoder.encode_message(
                    signed_message, message_type
                )
                new_packet = packet_pb2.Packet(
                    data=encoded, from_port=packet.from_port, to_port=packet.to_port
                )
                return new_packet.data, self.delays[index], 1

            elif isinstance(message, ripple_pb2.TMValidation):
                # logger.debug("Processing TMValidation for possible mutation")
                parsed = self.parse_validation_content(message)
                if "error" in parsed:
                    logger.error(f"Parsing validation failed: {parsed['error']}")
                    return packet.data, self.delays[index], 1
                # cache old validations
                lh = parsed.get("LedgerHash") if isinstance(parsed, dict) else None
                ldgr_seq = parsed.get("LedgerSequence") if isinstance(parsed, dict) else None
                if ldgr_seq not in self.old_validation_hashes:
                    self.old_validation_hashes[ldgr_seq] = set()
                if lh:
                    self.old_validation_hashes[ldgr_seq].add(lh)

                    
                # logger.debug(f"Parsed validation content: {parsed}")
                _pub_key = parsed.get("SigningPubKey", "")
                original_sender = self.pubkey_to_node_id(_pub_key)
                # logger.debug(f"Original sender node id: {original_sender}")
                if original_sender not in self.byzz_nodes:
                    # only mutate if sender is byzz node
                    return packet.data, self.delays[index], 1
                # logger.debug(
                #     f"Mutating validation from non-byzz node {original_sender}, sender_node_id={sender_node_id}"
                # )
                method = random.choice(
                    self.byzz_mutate_methods[ripple_pb2.TMProposeSet]
                )
                is_mutated = False
                if method == "do_nothing":
                    pass
                elif method == "increment_ledger_sequence":
                    try:
                        parsed["LedgerSequence"] = (
                            int(parsed.get("LedgerSequence", 0)) + 1
                        )
                        # logger.debug("Byzz mutate method: increment_ledger_sequence")
                        is_mutated = True
                    except Exception:
                        logger.error(
                            f"incrementing ledger sequence failed for {parsed.get('LedgerSequence','N/A')}"
                        )
                        assert False
                elif method == "replace_ledger_hash":
                    # 获取ldgr_seq的旧hash列表，选择一个不同于当前hash的hash
                    # logger.debug("Byzz mutate method: replace_ledger_hash")
                    current_hash = parsed.get("LedgerHash", "")
                    old_hashes = self.old_validation_hashes.get(ldgr_seq, set())
                    candidate_hashes = [h for h in old_hashes if h != current_hash]
                    if candidate_hashes:
                        parsed["LedgerHash"] = random.choice(candidate_hashes)
                    else:
                        parsed["LedgerHash"] = self.dummy_validation
                    is_mutated = True
                elif method == "replace_ledger_hash_with_dummy":
                    # logger.debug("Byzz mutate method: replace_ledger_hash_with_dummy")
                    parsed["LedgerHash"] = self.dummy_validation
                    is_mutated = True
                elif method == "repeat_5":
                    return packet.data, self.delays[index], 5
                if is_mutated:
                    signed_message = PacketEncoderDecoder.sign_message(
                        parsed, self.network.public_to_private_key_map[_pub_key]
                    )
                else:
                    signed_message = message

                encoded = PacketEncoderDecoder.encode_message(
                    signed_message, message_type
                )
                new_packet = packet_pb2.Packet(
                    data=encoded, from_port=packet.from_port, to_port=packet.to_port
                )
                return new_packet.data, self.delays[index], 1

            else:
                return packet.data, self.delays[index], 1

        return packet.data, self.delays[index], 1

    def _increment_propose_seq(self, message: ripple_pb2.TMProposeSet):
        if message.proposeSeq < MAX_U32:
            message.proposeSeq += 1
        return message

    def _replace_txs_with_old_propose(self, message: ripple_pb2.TMProposeSet):
        # 如果message.currentTxHash是全0，则设为self.dummy_proposal，否则设为上一个缓存的proposal
        if _is_all_zero_hash(message.currentTxHash):
            message.currentTxHash = self.dummy_proposal
        else:
            seq = message.proposeSeq - 1
            # 从self.old_proposals中选择一个不同于当前hash的proposal
            old_hashes = self.old_proposals.get(seq, set())
            candidate_hashes = [h for h in old_hashes if h != message.currentTxHash]
            if candidate_hashes:
                message.currentTxHash = random.choice(candidate_hashes)
            else:
                message.currentTxHash = self.dummy_proposal
        return message



    def pubkey_to_node_id(self, signing_pub: Any) -> int | None:
        """Return the node id for a given SigningPubKey (hex/base58/loose string).

        Returns None if no matching node is found. This mirrors how
        NetworkManager.update_network decodes base58 validator public keys.
        """
        signing_pub_hex = _normalize_pubhex(signing_pub)
        if not signing_pub_hex:
            return None

        # Try to match against the configured validator list by decoding
        # each node's base58 public key (as NetworkManager does) and
        # comparing the raw hex.
        for idx, node in enumerate(self.network.validator_node_list or []):
            try:
                decoded_pub = base58.b58decode(
                    node.validator_key_data.validation_public_key,
                    alphabet=base58.XRP_ALPHABET,
                )[1:34].hex()
            except Exception:
                continue
            if decoded_pub.lower() == signing_pub_hex.lower():
                return idx
        return None

   

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
                logger.error(f"Signature mismatch for node {sender_node_id} proposeSeq {message.proposeSeq}")

        if message_type == 41:
            parsed = self.parse_validation_content(message)
            print(f"Testing signing and round-trip for node {sender_node_id} sequence {parsed.get('LedgerSequence','N/A')}")

            # --- Round-trip serialization test ---
            try:
                # serialize the parsed dict (the serialize library handles the
                # canonical form including the signature field), compare to raw bytes
                reconstructed = bytes(serialize.serialize_bytes(parsed))
                orig_validation_bytes = getattr(message, "validation", b"")

                if orig_validation_bytes and reconstructed != orig_validation_bytes:
                    logger.error(
                        f"ROUNDTRIP_MISMATCH node={self.network.port_to_id(packet.from_port)} "
                        f"ledger={parsed.get('LedgerSequence','N/A')} len_orig={len(orig_validation_bytes)} len_recon={len(reconstructed)}"
                    )
                else:
                    print(f"\tround-trip\tSUCCESS")
            except Exception as e:
                print(f"roundtrip test failed: {e}")

            # Prefer to lookup the private key via the SigningPubKey extracted
            # from the parsed validation (this mirrors how ProposeSet uses
            # message.nodePubKey). Fall back to node_id-based lookup if the
            # public key is missing or not mapped.
            # Prefer to lookup the private key via the SigningPubKey extracted
            # from the parsed validation (this mirrors how ProposeSet uses
            # message.nodePubKey).
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
                logger.error(
                    f"Missing private key mapping for SigningPubKey {signing_pub_hex} (node {sender_node_id}). Skipping validation signing checks."
                )
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
                print(f"\tvalidation signature\tSUCCESS")


def _is_all_zero_hash(val) -> bool:
    """Return True if `val` represents an all-zero 32-byte hash.

    Handles:
    - bytes (binary) -> checks all bytes == 0
    - hex string (maybe with 0x, maybe mixed case) -> parses hex and checks == 0
    - empty / None -> treated as all-zero (adjust if you prefer otherwise)
    - returns False for non-hex strings
    """
    if val is None:
        return True

    # bytes-like
    if isinstance(val, (bytes, bytearray)):
        # if it looks like an ASCII hex string encoded as bytes (b'00...'), try decode
        try:
            s = val.decode('ascii')
        except Exception:
            # real binary bytes: check all bytes == 0
            return all(b == 0 for b in val)
        # if decoding succeeded and it's hex-like, fall through to string handling
        val = s

    # string-like (hex text)
    if isinstance(val, str):
        s = val.strip()
        # remove leading "0x" if present
        if s.startswith(("0x", "0X")):
            s = s[2:]
        # strip any non-hex characters (safe guard)
        s = re.sub(r'[^0-9A-Fa-f]', '', s)
        if s == '':
            # empty after sanitizing -> treat as all-zero (change if you prefer)
            return True
        # ensure even length
        if len(s) % 2 == 1:
            s = '0' + s
        try:
            return int(s, 16) == 0
        except ValueError:
            return False

    # anything else -> not all-zero
    return False
