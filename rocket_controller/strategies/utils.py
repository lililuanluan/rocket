from typing import Any, Dict, Tuple
import re
from protos import packet_pb2, ripple_pb2
from rocket_controller.encoder_decoder import (
    DecodingNotSupportedError,
    PacketEncoderDecoder,
    ValidationDict,
)
from rocket_controller.strategies.strategy import Strategy
import base58
from rocket_controller.helper import MAX_U32
import random


def normalize_pubhex(val: Any) -> str:
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
        s_sanitized = re.sub(r"[^0-9A-Fa-f]", "", s)
        return s_sanitized.lower()
    return str(val).lower()


BYZZ_MUTATE_METHODS = {
    # TODO: add mutation for TMGetLedger and TMLedgerData
    ripple_pb2.TMProposeSet: [
        "do_nothing",
        "replace_tx_hash",
        "increment_propose_seq",
        # "repeat_5",
        "drop",
    ],
    ripple_pb2.TMValidation: [
        "do_nothing",
        "replace_ledger_hash",
        "replace_ledger_hash_with_dummy",
        "increment_ledger_sequence",
        # "repeat_5",
        "drop",
    ],
}


class ByzzMutator:
    def __init__(self, strategy: Strategy):
        self.strategy = strategy
        self.byzz_mutate_methods = BYZZ_MUTATE_METHODS
        # TODO 确保strategy对象有一些属性，比如old_proposals, dummy_proposal等  

    def is_sent_from_byzz_node(self, _pub_key: Any) -> bool:
        # Resolve the original sender node id from the signing pubkey using
        # the associated Strategy instance (self.strategy). The previous
        # implementation passed the mutator object itself which lacks the
        # required network/validator list and caused incorrect results or
        # exceptions at runtime.
        original_sender = pubkey_to_node_id(self.strategy, _pub_key)
        if original_sender is None:
            return False
        return original_sender in (self.strategy.byzz_nodes or [])

    def get_random_mutation_method(self, message) -> str:
        if isinstance(message, ripple_pb2.TMProposeSet):
            message_type = ripple_pb2.TMProposeSet
        elif isinstance(message, ripple_pb2.TMValidation):
            message_type = ripple_pb2.TMValidation
        else:
            raise ValueError(f"Unsupported message type for mutation: {type(message)}")
        return random.choice(self.byzz_mutate_methods[message_type])

    def mutate_propose_set(
        self, message: ripple_pb2.TMProposeSet, method: str
    ) -> Tuple[Any, Any, Any]:
        def sign_message(message):
            return PacketEncoderDecoder.sign_message(
                message,
                self.strategy.network.public_to_private_key_map[
                    message.nodePubKey.hex()
                ],
            )

        if method == "do_nothing":
            return None, None, None

        elif method == "replace_tx_hash":
            message = replace_txs_with_old_propose(
                message,
                self.strategy.old_proposals,
                self.strategy.dummy_proposal,
            )
            signed_message = sign_message(message)
            return signed_message, None, None
        elif method == "increment_propose_seq":
            message = increment_propose_seq(message)
            signed_message = sign_message(message)
            return signed_message, None, None
        elif method == "repeat_5":
            return None, None, 5
        elif method == "drop":
            return None, MAX_U32, None
        else:
            raise ValueError(f"Unsupported mutation method for TMProposeSet: {method}")

    def mutate_validation(
        self, message: ripple_pb2.TMValidation, method: str
    ) -> Tuple[Any, Any, Any]:
        def sign_message(parsed):
            return PacketEncoderDecoder.sign_message(
                parsed,
                self.strategy.network.public_to_private_key_map[
                    normalize_pubhex(parsed.get("SigningPubKey", ""))
                ],
            )
        parsed = PacketEncoderDecoder.decode_validation(message)
        ldgr_seq = parsed.get("LedgerSequence")
        if method == "do_nothing":
            return None, None, None
        elif method == "increment_ledger_sequence":
            parsed["LedgerSequence"] = int(parsed.get("LedgerSequence", 0)) + 1
            return sign_message(parsed), None, None
        elif method == "replace_ledger_hash":
            current_hash = parsed.get("LedgerHash", "")
            old_hashes = self.strategy.old_validation_hashes.get(ldgr_seq, set())
            candidate_hashes = [h for h in old_hashes if h != current_hash]
            if candidate_hashes:
                parsed["LedgerHash"] = random.choice(candidate_hashes)
            else:
                parsed["LedgerHash"] = self.strategy.dummy_validation
            return sign_message(parsed), None, None
        elif method == "replace_ledger_hash_with_dummy":
            parsed["LedgerHash"] = self.strategy.dummy_validation
            return sign_message(parsed), None, None
        elif method == "repeat_5":
            return None, None, 5
        elif method == "drop":
            return None, MAX_U32, None
        else:
            raise ValueError(f"Unsupported mutation method for TMValidation: {method}")
            
            

    def mutate(self, message, method=None) -> Tuple[Any, Any, Any]:
        """
        return: mutated|None, delay|None, repeat|None
        """
        if method is None:
            method = self.get_random_mutation_method(type(message))

        if isinstance(message, ripple_pb2.TMProposeSet):
            return self.mutate_propose_set(message, method)
        elif isinstance(message, ripple_pb2.TMValidation):
            return self.mutate_validation(message, method)
        else:
            raise ValueError(f"Unsupported message type for mutation: {type(message)}")


def get_node_private_key(strategy: Strategy, node_id: int) -> str:
    if node_id < 0 or node_id >= len(strategy.network.validator_node_list):
        raise ValueError(f"Invalid node_id: {node_id}")

    return strategy.network.validator_node_list[
        node_id
    ].validator_key_data.validation_private_key


def pubkey_to_node_id(strategy: Strategy, signing_pub: Any) -> int | None:
    signing_pub_hex = normalize_pubhex(signing_pub)
    if not signing_pub_hex:
        return None

    # Try to match against the configured validator list by decoding
    # each node's base58 public key (as NetworkManager does) and
    # comparing the raw hex.
    for idx, node in enumerate(strategy.network.validator_node_list or []):
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


def increment_propose_seq(message: ripple_pb2.TMProposeSet):
    if message.proposeSeq < MAX_U32:
        message.proposeSeq += 1
    return message


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
            s = val.decode("ascii")
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
        s = re.sub(r"[^0-9A-Fa-f]", "", s)
        if s == "":
            # empty after sanitizing -> treat as all-zero (change if you prefer)
            return True
        # ensure even length
        if len(s) % 2 == 1:
            s = "0" + s
        try:
            return int(s, 16) == 0
        except ValueError:
            return False

    # anything else -> not all-zero
    return False


def replace_txs_with_old_propose(
    message: ripple_pb2.TMProposeSet,
    old_proposals: dict[int, set[bytes]],
    dummy_proposal: bytes,
) -> ripple_pb2.TMProposeSet:
    # 如果message.currentTxHash是全0，则设为self.dummy_proposal，否则设为上一个缓存的proposal
    if _is_all_zero_hash(message.currentTxHash):
        message.currentTxHash = dummy_proposal
    else:
        seq = message.proposeSeq - 1
        # 从old_proposals中选择一个不同于当前hash的proposal
        old_hashes = old_proposals.get(seq, set())
        candidate_hashes = [h for h in old_hashes if h != message.currentTxHash]
        if candidate_hashes:
            message.currentTxHash = random.choice(candidate_hashes)
        else:
            message.currentTxHash = dummy_proposal
    return message
