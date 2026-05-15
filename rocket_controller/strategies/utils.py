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
from loguru import logger
import copy
from threading import Lock


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
    ripple_pb2.TMStatusChange: [
        "do_nothing",
        "replace_ledger_hash_with_dummy",
        "replace_prev_lgr_hash_with_dummy",
        "increment_ledger_sequence",
        "replace_event_with_lost_sync",
        # Future candidates:
        # "decrement_ledger_sequence",
        # "replace_event_with_switched_ledger",
        # "replace_status_with_monitoring",
        # "replace_status_with_shutting",
        # "skew_network_time",
        # "replace_seq_range",
        "drop",
    ],
    ripple_pb2.TMLedgerData: [
        "do_nothing",
        "set_error_no_ledger",
        "clear_nodes",
        "replace_cookie_with_prev",
        "replace_ledger_hash_with_dummy",
        # Future candidates:
        # "set_error_no_node",
        # "drop_first_node",
        # "duplicate_first_node",
        # "corrupt_first_node_id",
        # "corrupt_first_node_data",
        # "increment_ledger_sequence",
        # "replace_type_with_candidate",
        "drop",
    ],
    ripple_pb2.TMGetLedger: [
        "do_nothing",
        "replace_ledger_hash_with_dummy",
        "replace_ledger_sequence_with_high",
        "clear_nodeIDs",
        "replace_cookie_with_prev",
    ],
    ripple_pb2.TMProposeSet: [
        "do_nothing",
        "replace_tx_hash",
        "increment_close_time_bucket",
        "decrement_close_time_bucket",
        "replace_close_time_with_old",
        "replace_prev_lgr_hash",
        "increment_propose_seq",
        # "repeat_5",
        "drop",
    ],
    ripple_pb2.TMValidation: [
        "do_nothing",
        "replace_ledger_hash",
        "replace_ledger_hash_with_dummy",
        "increment_ledger_sequence",
        # "increment_signing_time", # TODO bug
        # "flip_flags",
        # "repeat_5",
        # TODO closing time
        "drop",
    ],
    ripple_pb2.TMHaveTransactionSet: [
        "do_nothing",
        "drop",
        "to_tsneed_dummy",
    ],
    ripple_pb2.TMTransaction: [
        "do_nothing",
        "drop",
        "replace_tx_hash",
    ],
}


class ByzzMutator:
    def __init__(
        self, strategy: Strategy
    ):  # use EvodealyStrategy would cause circular import
        self.strategy = strategy
        self.byzz_mutate_methods = BYZZ_MUTATE_METHODS
        self.lock = Lock()
        # TODO 确保strategy对象有一些属性，比如old_proposals, dummy_proposal等

        self.log_debug = False

    def debug(self, *args):
        if self.log_debug:
            logger.debug(*args)

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
        if type(message) not in self.byzz_mutate_methods:
            logger.error(
                f"No mutation methods defined for message type: {type(message)}"
            )
            raise ValueError(
                f"No mutation methods defined for message type: {type(message)}"
            )

        return random.choice(self.byzz_mutate_methods[type(message)])

    def get_mutation_method_50_percent(self, message) -> str:
        # 50 % do_nothing, 50 % random other
        if type(message) not in self.byzz_mutate_methods:
            logger.error(
                f"No mutation methods defined for message type: {type(message)}"
            )
            raise ValueError(
                f"No mutation methods defined for message type: {type(message)}"
            )

        if random.random() < 0.5:
            return "do_nothing"
        return random.choice(
            [i for i in self.byzz_mutate_methods[type(message)] if i != "do_nothing"]
        )

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

        # Work on a deep copy to avoid mutating caller-owned protobuf objects in-place
        msg_copy = copy.deepcopy(message)

        if method == "do_nothing":
            return None, None, None

        elif method == "replace_tx_hash":
            self.debug("Mutate TMProposeSet: replace_tx_hash")
            with self.lock:
                # replace_txs_with_old_propose returns a new message (non-destructive)
                new_msg = replace_txs_with_old_propose(
                    msg_copy,
                    self.strategy.old_proposals,
                    self.strategy.dummy_proposal,
                )
            signed_message = sign_message(new_msg)
            return signed_message, None, None
        elif method == "increment_close_time_bucket":
            self.debug("Mutate TMProposeSet: increment_close_time_bucket")
            new_msg = shift_proposal_close_time_bucket(msg_copy, 10)
            signed_message = sign_message(new_msg)
            return signed_message, None, None
        elif method == "decrement_close_time_bucket":
            self.debug("Mutate TMProposeSet: decrement_close_time_bucket")
            new_msg = shift_proposal_close_time_bucket(msg_copy, -10)
            signed_message = sign_message(new_msg)
            return signed_message, None, None
        elif method == "replace_close_time_with_old":
            self.debug("Mutate TMProposeSet: replace_close_time_with_old")
            with self.lock:
                new_msg = replace_close_time_with_old_propose(
                    msg_copy,
                    self.strategy.old_proposal_close_times,
                )
            signed_message = sign_message(new_msg)
            return signed_message, None, None
        elif method == "replace_prev_lgr_hash":
            self.debug("Mutate TMProposeSet: replace_prev_lgr_hash")
            with self.lock:
                new_msg = replace_prev_lgr_hash_with_old_propose(
                    msg_copy,
                    getattr(self.strategy, "old_proposal_prev_ledger_hashes", {}),
                    getattr(self.strategy, "old_validation_hashes", {}),
                    self.strategy.dummy_proposal,
                )
            signed_message = sign_message(new_msg)
            return signed_message, None, None
        elif method == "increment_propose_seq":
            self.debug("Mutate TMProposeSet: increment_propose_seq")
            new_msg = increment_propose_seq(msg_copy)
            signed_message = sign_message(new_msg)
            return signed_message, None, None
        elif method == "repeat_5":
            self.debug("Mutate TMProposeSet: repeat_5")
            return None, None, 5
        elif method == "drop":
            self.debug("Mutate TMProposeSet: drop")
            return None, MAX_U32, 0
        else:
            raise ValueError(f"Unsupported mutation method for TMProposeSet: {method}")

    def mutate_validation(
        self, message: ripple_pb2.TMValidation, method: str
    ) -> Tuple[Any, Any, Any]:
        def sign_message(parsed):
            private_key = self.strategy.network.public_to_private_key_map[
                normalize_pubhex(parsed["SigningPubKey"])
            ]
            return PacketEncoderDecoder.sign_message(
                parsed,
                private_key,
            )

        parsed = PacketEncoderDecoder.decode_validation(message)
        ldgr_seq = parsed.get("LedgerSequence")
        if method == "do_nothing":
            return None, None, None
        elif method == "increment_ledger_sequence":
            self.debug("Mutate TMValidation: increment_ledger_sequence")
            parsed["LedgerSequence"] = int(parsed.get("LedgerSequence", 0)) + 1
            return sign_message(parsed), None, None
        elif method == "replace_ledger_hash":
            self.debug("Mutate TMValidation: replace_ledger_hash")
            current_hash = parsed.get("LedgerHash", "")
            with self.lock:
                old_hashes = self.strategy.old_validation_hashes.get(ldgr_seq, set())
            candidate_hashes = [h for h in old_hashes if h != current_hash]
            if candidate_hashes:
                parsed["LedgerHash"] = random.choice(candidate_hashes)
            else:
                parsed["LedgerHash"] = self.strategy.dummy_validation
            return sign_message(parsed), None, None
        elif method == "replace_ledger_hash_with_dummy":
            self.debug("Mutate TMValidation: replace_ledger_hash_with_dummy")
            parsed["LedgerHash"] = self.strategy.dummy_validation
            return sign_message(parsed), None, None
        elif method == "increment_signing_time":
            self.debug("Mutate TMValidation: increment_signing_time")
            parsed["SigningTime"] = int(parsed.get("SigningTime", 0)) + 1
            return sign_message(parsed), None, None
        elif method == "flip_flags":
            self.debug("Mutate TMValidation: flip_flags")
            # flip a bit of parsed["Flags"]
            flags = int(parsed.get("Flags", 0))
            bit_to_flip = 1 << random.randint(0, 31)
            parsed["Flags"] = flags ^ bit_to_flip
            return sign_message(parsed), None, None
        elif method == "repeat_5":
            self.debug("Mutate TMValidation: repeat_5")
            return None, None, 5
        elif method == "drop":
            self.debug("Mutate TMValidation: drop")
            return None, MAX_U32, 0
        else:
            logger.error(f"Unsupported mutation method for TMValidation: {method}")
            raise ValueError(f"Unsupported mutation method for TMValidation: {method}")

    def mutate_have_transaction_set(
        self, message: ripple_pb2.TMHaveTransactionSet, method: str
    ) -> Tuple[Any, Any, Any]:
        # avoid mutating the incoming protobuf in-place
        if method == "do_nothing":
            return None, None, None
        elif method == "drop":
            return None, MAX_U32, 0
        elif method == "to_tsneed_dummy":
            # Work on a copy and return it
            msg_copy = copy.deepcopy(message)
            # Use the generated enum constant from the ripple_pb2 module
            msg_copy.status = ripple_pb2.tsNEED  # tsCAN_GET tsHAVE
            msg_copy.hash = bytes.fromhex(
                "e803e1999369975aed1bfd2444a3552a73383c03a2004cb784ce07e13ebd7d7c"
            )
            return msg_copy, None, None
        else:
            logger.error(
                f"Unsupported mutation method for TMHaveTransactionSet: {method}"
            )
            raise ValueError(
                f"Unsupported mutation method for TMHaveTransactionSet: {method}"
            )

    def mutate_transaction(
        self, message: ripple_pb2.TMTransaction, method: str
    ) -> Tuple[Any, Any, Any]:
        if method == "do_nothing":
            return None, None, None
        elif method == "drop":
            return None, MAX_U32, 0
        elif method == "replace_tx_hash":
            msg_copy = copy.deepcopy(message)
            # Replace the transaction blob with a previously seen transaction hash or dummy
            prev_tx = None
            for tx in self.strategy.old_transactions:
                # old_transactions stores hex strings of rawTransaction (message.rawTransaction.hex())
                # compare against msg_copy.rawTransaction.hex() to avoid AttributeError
                current_tx_hex = msg_copy.rawTransaction.hex()
                if current_tx_hex is None or tx != current_tx_hex:
                    prev_tx = tx
                    break
            if prev_tx is None:
                prev_tx = self.strategy.dummy_transaction
            msg_copy.rawTransaction = bytes.fromhex(prev_tx)
            return msg_copy, None, None
        else:
            logger.error(f"Unsupported mutation method for TMTransaction: {method}")
            raise ValueError(f"Unsupported mutation method for TMTransaction: {method}")

    def mutate_status_change(
        self, message: ripple_pb2.TMStatusChange, method: str
    ) -> Tuple[Any, Any, Any]:
        if method == "do_nothing":
            return None, None, None
        elif method == "replace_ledger_hash_with_dummy":
            msg_copy = copy.deepcopy(message)
            msg_copy.ledgerHash = bytes.fromhex(self.strategy.dummy_hash)
            return msg_copy, None, None
        elif method == "replace_prev_lgr_hash_with_dummy":
            msg_copy = copy.deepcopy(message)
            msg_copy.ledgerHashPrevious = bytes.fromhex(self.strategy.dummy_hash)
            return msg_copy, None, None
        elif method == "increment_ledger_sequence":
            msg_copy = copy.deepcopy(message)
            if msg_copy.ledgerSeq < MAX_U32:
                msg_copy.ledgerSeq += 1
            return msg_copy, None, None
        elif method == "replace_event_with_lost_sync":
            msg_copy = copy.deepcopy(message)
            msg_copy.newEvent = ripple_pb2.neLOST_SYNC
            return msg_copy, None, None
        elif method == "drop":
            return None, MAX_U32, 0
        else:
            logger.error(f"Unsupported mutation method for TMStatusChange: {method}")
            raise ValueError(f"Unsupported mutation method for TMStatusChange: {method}")

    def mutate_ledger_data(
        self, message: ripple_pb2.TMLedgerData, method: str
    ) -> Tuple[Any, Any, Any]:
        if method == "do_nothing":
            return None, None, None
        elif method == "set_error_no_ledger":
            msg_copy = copy.deepcopy(message)
            msg_copy.error = ripple_pb2.reNO_LEDGER
            del msg_copy.nodes[:]
            return msg_copy, None, None
        elif method == "clear_nodes":
            msg_copy = copy.deepcopy(message)
            del msg_copy.nodes[:]
            return msg_copy, None, None
        elif method == "replace_cookie_with_prev":
            msg_copy = copy.deepcopy(message)
            current_cookie = int(msg_copy.requestCookie)
            with self.lock:
                old_cookies = list(getattr(self.strategy, "old_ledger_data_cookies", []))
            candidate_cookies = [c for c in old_cookies if int(c) != current_cookie]
            if candidate_cookies:
                msg_copy.requestCookie = int(random.choice(candidate_cookies))
            else:
                msg_copy.requestCookie = random.randint(1, MAX_U32)
            return msg_copy, None, None
        elif method == "replace_ledger_hash_with_dummy":
            msg_copy = copy.deepcopy(message)
            msg_copy.ledgerHash = bytes.fromhex(self.strategy.dummy_hash)
            return msg_copy, None, None
        elif method == "drop":
            return None, MAX_U32, 0
        else:
            logger.error(f"Unsupported mutation method for TMLedgerData: {method}")
            raise ValueError(f"Unsupported mutation method for TMLedgerData: {method}")

    def mutate_get_ledger(
        self, message: ripple_pb2.TMGetLedger, method: str
    ) -> Tuple[Any, Any, Any]:
        # if method != "do_nothing":
        #     logger.error(f"Mutating TMGetLedger with method: {method}")
        if method == "do_nothing":
            # logger.error(f"[TMGetLedger] do_nothing, original: ledgerHash={getattr(message, 'ledgerHash', None)}, ledgerSeq={getattr(message, 'ledgerSeq', None)}, nodeIDs={list(getattr(message, 'nodeIDs', []))}, requestCookie={getattr(message, 'requestCookie', None)}")
            return None, None, None
        elif method == "replace_ledger_hash_with_dummy":
            msg_copy = copy.deepcopy(message)
            msg_copy.ledgerHash = bytes.fromhex(self.strategy.dummy_hash)
            # logger.debug(f"[TMGetLedger] replace_ledger_hash_with_dummy: ledgerHash={msg_copy.ledgerHash.hex()}")
            return msg_copy, None, None
        elif method == "replace_ledger_sequence_with_high":
            msg_copy = copy.deepcopy(message)
            msg_copy.ledgerSeq = MAX_U32
            # logger.debug(f"[TMGetLedger] replace_ledger_sequence_with_high: ledgerSeq={msg_copy.ledgerSeq}")
            return msg_copy, None, None
        elif method == "clear_nodeIDs":
            msg_copy = copy.deepcopy(message)
            before = list(msg_copy.nodeIDs)
            del msg_copy.nodeIDs[:]
            # logger.debug(f"[TMGetLedger] clear_nodeIDs: before={before}, after={list(msg_copy.nodeIDs)}")
            return msg_copy, None, None
        elif method == "replace_cookie_with_prev":
            msg_copy = copy.deepcopy(message)
            with self.lock:
                prev_cookie = (
                    self.strategy.old_get_ledger[-1][1]
                    if self.strategy.old_get_ledger
                    else None
                )
                if prev_cookie is not None:
                    msg_copy.requestCookie = prev_cookie
                else:
                    msg_copy.requestCookie = random.randint(1, MAX_U32)
            # logger.debug(
            #     f"[TMGetLedger] replace_cookie_with_prev: requestCookie={msg_copy.requestCookie}"
            # )
            return msg_copy, None, None
        else:
            logger.error(f"Unsupported mutation method for TMGetLedger: {method}")
            raise ValueError(f"Unsupported mutation method for TMGetLedger: {method}")

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
        elif isinstance(message, ripple_pb2.TMHaveTransactionSet):
            return self.mutate_have_transaction_set(message, method)
        elif isinstance(message, ripple_pb2.TMTransaction):
            return self.mutate_transaction(message, method)
        elif isinstance(message, ripple_pb2.TMStatusChange):
            return self.mutate_status_change(message, method)
        elif isinstance(message, ripple_pb2.TMLedgerData):
            return self.mutate_ledger_data(message, method)
        elif isinstance(message, ripple_pb2.TMGetLedger):
            return self.mutate_get_ledger(message, method)
        else:
            logger.error(f"Unsupported message type for mutation: {type(message)}")
            raise ValueError(f"Unsupported message type for mutation: {type(message)}")


def get_node_private_key(strategy: Strategy, node_id: int) -> str:
    if node_id < 0 or node_id >= len(strategy.network.validator_node_list):
        logger.error(f"Invalid node_id: {node_id}")
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
    # operate on a copy to avoid in-place mutation
    m = copy.deepcopy(message)
    if m.proposeSeq < MAX_U32:
        m.proposeSeq += 1
    return m


def shift_proposal_close_time_bucket(
    message: ripple_pb2.TMProposeSet, delta_seconds: int
) -> ripple_pb2.TMProposeSet:
    """Shift a proposal close time by one or more consensus buckets.

    We mutate by bucket-sized deltas instead of single-second nudges because
    bucket changes are more likely to influence close-time voting.
    """
    m = copy.deepcopy(message)
    shifted = int(m.closeTime) + int(delta_seconds)
    m.closeTime = max(0, shifted)
    return m


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


def _hash_to_bytes(val: Any) -> bytes | None:
    if val is None:
        return None
    if isinstance(val, (bytes, bytearray)):
        hash_bytes = bytes(val)
    elif isinstance(val, str):
        s = val.strip()
        if s.startswith(("0x", "0X")):
            s = s[2:]
        s = re.sub(r"[^0-9A-Fa-f]", "", s)
        if len(s) % 2 == 1:
            s = "0" + s
        try:
            hash_bytes = bytes.fromhex(s)
        except ValueError:
            return None
    else:
        return None

    if len(hash_bytes) != 32:
        return None
    return hash_bytes


def _hash_candidates_excluding(current: bytes, values) -> list[bytes]:
    candidates = []
    for value in values:
        hash_bytes = _hash_to_bytes(value)
        if hash_bytes is not None and hash_bytes != current:
            candidates.append(hash_bytes)
    return candidates


def replace_txs_with_old_propose(
    message: ripple_pb2.TMProposeSet,
    old_proposals: dict[int, set[bytes]],
    dummy_proposal: bytes,
) -> ripple_pb2.TMProposeSet:
    # Return a modified copy of the message to avoid mutating the caller's object.
    m = copy.deepcopy(message)
    # 如果message.currentTxHash是全0，则设为 dummy_proposal，否则设为上一个缓存的proposal
    if _is_all_zero_hash(m.currentTxHash):
        m.currentTxHash = dummy_proposal
    else:
        seq = m.proposeSeq - 1
        # 从old_proposals中选择一个不同于当前hash的proposal
        old_hashes = old_proposals.get(seq, set())
        candidate_hashes = [h for h in old_hashes if h != m.currentTxHash]
        if candidate_hashes:
            m.currentTxHash = random.choice(candidate_hashes)
        else:
            m.currentTxHash = dummy_proposal
    return m


def replace_close_time_with_old_propose(
    message: ripple_pb2.TMProposeSet,
    old_close_times: dict[int, set[int]],
) -> ripple_pb2.TMProposeSet:
    """Reuse an earlier proposal close time from the same consensus round.

    Preference order:
    1. Previous proposal sequence in the round (`proposeSeq - 1`)
    2. Same proposal sequence observed from other peers
    If neither yields a different close time, keep the current one.
    """
    m = copy.deepcopy(message)
    current_close_time = int(m.closeTime)

    candidate_close_times = [
        ct
        for ct in old_close_times.get(m.proposeSeq - 1, set())
        if int(ct) != current_close_time
    ]
    if not candidate_close_times:
        candidate_close_times = [
            ct
            for ct in old_close_times.get(m.proposeSeq, set())
            if int(ct) != current_close_time
        ]

    if candidate_close_times:
        m.closeTime = int(random.choice(candidate_close_times))
    return m


def replace_prev_lgr_hash_with_old_propose(
    message: ripple_pb2.TMProposeSet,
    old_prev_ledger_hashes: dict[int, set[bytes]],
    old_validation_hashes: dict[int, set[str]],
    dummy_prev_lgr_hash: bytes,
) -> ripple_pb2.TMProposeSet:
    """Replace a proposal parent ledger hash with an observed alternative.

    Validations do not carry a previous-ledger field in the decoded form; their
    LedgerHash can still serve as a plausible parent hash for later proposals.
    """
    m = copy.deepcopy(message)
    current_prev = bytes(m.previousledger)

    candidate_hashes = _hash_candidates_excluding(
        current_prev, old_prev_ledger_hashes.get(m.proposeSeq - 1, set())
    )
    if not candidate_hashes:
        candidate_hashes = _hash_candidates_excluding(
            current_prev, old_prev_ledger_hashes.get(m.proposeSeq, set())
        )
    if not candidate_hashes:
        all_prev_hashes = set()
        for hashes in old_prev_ledger_hashes.values():
            all_prev_hashes.update(hashes)
        candidate_hashes = _hash_candidates_excluding(current_prev, all_prev_hashes)
    if not candidate_hashes:
        all_validation_hashes = set()
        for hashes in old_validation_hashes.values():
            all_validation_hashes.update(hashes)
        candidate_hashes = _hash_candidates_excluding(current_prev, all_validation_hashes)

    if candidate_hashes:
        m.previousledger = random.choice(candidate_hashes)
    else:
        m.previousledger = dummy_prev_lgr_hash
    return m
