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

from google.protobuf.message import Message
import time

TMP_ERROR_FILE = Path(__file__).parent / "../../evo/out/error.log" # TODO add this as a param


from rocket_controller.strategies.utils import (
    normalize_pubhex,
    BYZZ_MUTATE_METHODS,
    get_node_private_key,
    pubkey_to_node_id,
    increment_propose_seq,
    replace_txs_with_old_propose,
    ByzzMutator
)


class EvoDelayStrategy(Strategy):
    """Class that implements an evolutionary delay-based strategy."""

    def __init__(
        self,
        network_config_path: str = "./config/network/default_network.yaml",
        **kwargs,
    ):
        super().__init__(network_config_path=network_config_path, **kwargs)

        self.encoding: dict = self.params["encoding"]
        self.byzz_min_seq: int = self.params.get("byzz_min_seq", 5)
        self.byzz_max_seq: int = self.params.get("byzz_max_seq", 10)
        self.seqcheck: str = str(self.params.get("seqcheck", "statuschange")).lower()
        if self.seqcheck not in ("fullyval", "statuschange"):
            raise ValueError(
                "Invalid seqcheck value. Expected one of: fullyval, statuschange"
            )


        self.dummy_hash = "E803E1999369975AED1BFD2444A3552A73383C03A2004CB784CE07E13EBD7D7C"
        self.dummy_proposal = bytes.fromhex(self.dummy_hash)
        self.dummy_validation = self.dummy_hash
        self.dummy_transaction = self.dummy_hash
        
        self.old_proposals = {-1: set([self.dummy_proposal,])} # seq -> set of proposals
        self.old_proposal_close_times = {-1: set()} # seq -> set of proposal close times
        self.old_proposal_prev_ledger_hashes = {-1: set([self.dummy_proposal,])} # seq -> set of proposal previous ledger hashes
        self.old_validation_hashes = {-1: set([self.dummy_validation,])} # seq -> set of validations
        self.old_status_ledger_hashes = {-1: set([self.dummy_proposal,])} # seq -> set of status ledger hashes
        self.old_status_prev_ledger_hashes = {-1: set([self.dummy_proposal,])} # seq -> set of status previous ledger hashes
        self.old_ledger_data_hashes = {-1: set([self.dummy_proposal,])} # seq -> set of ledger data hashes
        self.old_ledger_data_cookies = []
        self.old_transactions = []
        
        self.old_get_ledger = []

        self.byzz_mutate_methods = BYZZ_MUTATE_METHODS
        self.byzz_mutator = ByzzMutator(self)


    def setup(self):
        """Setup method for EvoDelayStrategy."""

        # Hardcoded on 7 message types we will consider, could be a parameter in the future
        assert len(self.encoding["delays"]) == 7 * self.network.node_amount * (
            self.network.node_amount - 1
        )



    # 拜占庭行为（byzzfuzz）：
    # transaction消息：更改交易的amount
    # proposeset：更改txs hash或者sequence number
    # validation：更改id（pubkey？）或者sequence number
    # 分为small scope和any scope
    # small scope：对数值+1，对hash替换为网络中的前一个hash

    def cache_old_messages(self, message: Message) -> dict | None:
        # TODO: could clear old cache for small scode mutations
        # for now: cache[seq] -> set()
        # cache old proposals
        if isinstance(message, ripple_pb2.TMProposeSet):
            prop_seq = message.proposeSeq
            if prop_seq not in self.old_proposals:
                self.old_proposals[prop_seq] = set()
            self.old_proposals[prop_seq].add(message.currentTxHash)
            if prop_seq not in self.old_proposal_close_times:
                self.old_proposal_close_times[prop_seq] = set()
            self.old_proposal_close_times[prop_seq].add(int(message.closeTime))
            if prop_seq not in self.old_proposal_prev_ledger_hashes:
                self.old_proposal_prev_ledger_hashes[prop_seq] = set()
            self.old_proposal_prev_ledger_hashes[prop_seq].add(bytes(message.previousledger))
        elif isinstance(message, ripple_pb2.TMValidation):
            parsed = PacketEncoderDecoder.decode_validation(message)
            if "error" in parsed:
                raise ValueError(
                    f"Failed to parse validation for caching: {parsed['error']}"
                )
            # cache old validations
            lh = parsed.get("LedgerHash") if isinstance(parsed, dict) else None
            ldgr_seq = (
                parsed.get("LedgerSequence") if isinstance(parsed, dict) else None
            )
            if ldgr_seq not in self.old_validation_hashes:
                self.old_validation_hashes[ldgr_seq] = set()
            if lh:
                self.old_validation_hashes[ldgr_seq].add(lh)
        elif isinstance(message, ripple_pb2.TMStatusChange):
            ledger_seq = int(message.ledgerSeq)
            if ledger_seq not in self.old_status_ledger_hashes:
                self.old_status_ledger_hashes[ledger_seq] = set()
            if message.ledgerHash:
                self.old_status_ledger_hashes[ledger_seq].add(bytes(message.ledgerHash))
            if ledger_seq not in self.old_status_prev_ledger_hashes:
                self.old_status_prev_ledger_hashes[ledger_seq] = set()
            if message.ledgerHashPrevious:
                self.old_status_prev_ledger_hashes[ledger_seq].add(
                    bytes(message.ledgerHashPrevious)
                )
        elif isinstance(message, ripple_pb2.TMLedgerData):
            ledger_seq = int(message.ledgerSeq)
            if ledger_seq not in self.old_ledger_data_hashes:
                self.old_ledger_data_hashes[ledger_seq] = set()
            if message.ledgerHash:
                self.old_ledger_data_hashes[ledger_seq].add(bytes(message.ledgerHash))
            request_cookie = int(message.requestCookie)
            if request_cookie not in self.old_ledger_data_cookies:
                self.old_ledger_data_cookies.append(request_cookie)
        elif isinstance(message, ripple_pb2.TMTransaction):
            tx = message.rawTransaction.hex()
            if tx not in self.old_transactions:
                self.old_transactions.append(tx)
        elif isinstance(message, ripple_pb2.TMGetLedger):
            # cache old get_ledger requests for possible mutation methods that replace with old values
            gl_tuple = (message.ledgerHash.hex(), message.requestCookie, message.queryType)
            if gl_tuple not in self.old_get_ledger:
                self.old_get_ledger.append(gl_tuple)


    def get_delay(self, message_type: int, packet: packet_pb2.Packet, current_ledger: int, message_cls: type) -> int:
        sender_node_id = self.network.port_to_id(packet.from_port)
        receiver_node_id = self.network.port_to_id(packet.to_port)
        # To get type index -> subtract 30, for validation, subtract 35
        type_id = message_type - 30 if message_type != 41 else 6
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
        return self.encoding["delays"][index]

    def get_partition_delay(self, cur_time) -> int:
        return 0

    def get_mutation_method(
        self,
        message,
        packet: packet_pb2.Packet | None = None,
        current_ledger: int | None = None,
    ) -> str:
        method = self.byzz_mutator.get_mutation_method_50_percent(message)
        return method

    def observe_packet_for_strategy_state(
        self,
        message: Message,
        packet: packet_pb2.Packet,
        current_ledger: int,
    ) -> None:
        return None
    
    def are_partitioned(self, sender_node_id, receiver_node_id):
        return False

    def _get_fully_validated_ledger(self, sender_node_id: int) -> int:
        try:
            return self.iteration_type.get_ledger_sequence(sender_node_id)
        except ValueError:
            return self.iteration_type.get_ledger_sequence_cur_max()

    def _get_status_change_ledger(
        self,
        sender_node_id: int,
        message: Message | None = None,
    ) -> int:
        try:
            current_ledger = self.iteration_type.get_status_change_sequence(
                sender_node_id
            )
        except ValueError:
            current_ledger = self.iteration_type.get_status_change_sequence_cur_max()

        if isinstance(message, ripple_pb2.TMStatusChange):
            current_ledger = max(current_ledger, int(message.ledgerSeq))

        if current_ledger > 0:
            return current_ledger
        return self._get_fully_validated_ledger(sender_node_id)

    def _get_current_ledger(
        self,
        sender_node_id: int,
        message: Message | None = None,
    ) -> int:
        if self.seqcheck == "fullyval":
            return self._get_fully_validated_ledger(sender_node_id)
        return self._get_status_change_ledger(sender_node_id, message)

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
        sender_node_id = self.network.port_to_id(packet.from_port)
        to_node_id = self.network.port_to_id(packet.to_port)

        try:
            self.cache_old_messages(message) # parse validation may fail
        except Exception as e:
            logger.error(f"Error caching old messages: {e}")
            return packet.data, 0, 1

        if message_type not in set(range(30, 36)).union({41}):
            delay = self.get_partition_delay(time.time()) if self.are_partitioned(sender_node_id, to_node_id) else 0
            return packet.data, delay, 1

        # Types used in evolutionary paper: https://doi.org/10.1109/ICSE-SEIP58684.2023.00009
        # 30: ripple_pb2.TMTransaction
        # 31: ripple_pb2.TMGetLedger
        # 32: ripple_pb2.TMLedgerData
        # 33: ripple_pb2.TMProposeSet
        # 34: ripple_pb2.TMStatusChange
        # 35: ripple_pb2.TMHaveTransactionSet
        # 41: ripple_pb2.TMValidation

        current_ledger = self._get_current_ledger(sender_node_id, message)

        self.observe_packet_for_strategy_state(message, packet, current_ledger)
        configed_delay = self.get_delay(message_type, packet, current_ledger, type(message))

        # # Debug logging for message routing
        # if isinstance(message, ripple_pb2.TMProposeSet):
        #     logger.debug(
        #         f"[ProposeSet] type={message_type}, sender={sender_node_id}, "
        #         f"receiver={receiver_node_id}, proposeSeq={message.proposeSeq}, "
        #         f"delay_index={index}, delay={self.delays[index]}ms, "
        #         f"current_ledger={current_ledger}, max_ledger={self.max_ledger_seq}"
        #     )
        # elif isinstance(message, ripple_pb2.TMValidation):
        #     logger.debug(
        #         f"[Validation] type={message_type}, sender={sender_node_id}, "
        #         f"receiver={receiver_node_id}, delay_index={index}, delay={self.delays[index]}ms"
        #     )

        # Apply mutation logic in window [byzz_min_seq, byzz_max_seq]

        def handle_mutated_message(mutated_message, mutated_delay, mutated_repeat):

            if mutated_message is None:
                mutated_message = message  
            if mutated_delay is None:
                mutated_delay = configed_delay
            if mutated_repeat is None:
                mutated_repeat = 1
            encoded = PacketEncoderDecoder.encode_message(
                mutated_message, message_type
            )
            new_packet = packet_pb2.Packet(
                data=encoded, from_port=packet.from_port, to_port=packet.to_port
            )
            return new_packet.data, mutated_delay, mutated_repeat


        if (
            self.byzz_min_seq
            <= current_ledger
            <= self.byzz_max_seq
        ):
            if isinstance(message, ripple_pb2.TMProposeSet):
                if sender_node_id not in (self.byzz_nodes or []):
                    return packet.data, configed_delay, 1

                # Only byzz senders may mutate proposals signed by the byzz coalition.
                _pub_key = message.nodePubKey.hex()
                original_sender = pubkey_to_node_id(self, _pub_key)
                if original_sender not in (self.byzz_nodes or []):
                    return packet.data, configed_delay, 1

                # logger.debug(
                #     f"Mutating propose from non-byzz node {original_sender}, sender_node_id={sender_node_id}"
                # )
                # message sent by byzz nodes:
                method = self.get_mutation_method(message, packet, current_ledger)

                signed_message, delay, repeat = self.byzz_mutator.mutate(message, method)
                return handle_mutated_message(signed_message, delay, repeat)

            elif isinstance(message, ripple_pb2.TMValidation): # TODO: 让parsed返回结果也继承自Message，统一接口
                if sender_node_id not in (self.byzz_nodes or []):
                    return packet.data, configed_delay, 1

                # logger.debug("Processing TMValidation for possible mutation")
                parsed = PacketEncoderDecoder.decode_validation(message)

                # logger.debug(f"Parsed validation content: {parsed}")
                _pub_key = parsed.get("SigningPubKey", "")
                original_sender = pubkey_to_node_id(self, _pub_key)
                if original_sender not in (self.byzz_nodes or []):
                    return packet.data, configed_delay, 1
                # logger.debug(
                #     f"Mutating validation from non-byzz node {original_sender}, sender_node_id={sender_node_id}"
                # )
                method = self.get_mutation_method(message, packet, current_ledger)

                signed_message, delay, repeat = self.byzz_mutator.mutate(message, method)
                return handle_mutated_message(signed_message, delay, repeat)
            elif isinstance(message, ripple_pb2.TMHaveTransactionSet):
                if sender_node_id not in (self.byzz_nodes or []):
                    return packet.data, configed_delay, 1
                method = self.get_mutation_method(message, packet, current_ledger)
                mutated_message, delay, repeat = self.byzz_mutator.mutate(message, method)

                # print(f"chosen mutation method: {method}")
                return handle_mutated_message(mutated_message, delay, repeat)
            elif isinstance(message, ripple_pb2.TMLedgerData):
                if sender_node_id not in (self.byzz_nodes or []):
                    return packet.data, configed_delay, 1
                method = self.get_mutation_method(message, packet, current_ledger)
                mutated_message, delay, repeat = self.byzz_mutator.mutate(message, method)
                return handle_mutated_message(mutated_message, delay, repeat)
            elif isinstance(message, ripple_pb2.TMStatusChange):
                if sender_node_id not in (self.byzz_nodes or []):
                    return packet.data, configed_delay, 1
                method = self.get_mutation_method(message, packet, current_ledger)
                mutated_message, delay, repeat = self.byzz_mutator.mutate(message, method)
                return handle_mutated_message(mutated_message, delay, repeat)
            elif isinstance(message, ripple_pb2.TMTransaction):
                if sender_node_id not in (self.byzz_nodes or []):
                    return packet.data, configed_delay, 1
                method = self.get_mutation_method(message, packet, current_ledger)
                mutated_message, delay, repeat = self.byzz_mutator.mutate(message, method)
                return handle_mutated_message(mutated_message, delay, repeat)
            elif isinstance(message, ripple_pb2.TMGetLedger):
                if sender_node_id not in (self.byzz_nodes or []):
                    return packet.data, configed_delay, 1
                method = self.get_mutation_method(message, packet, current_ledger)
                mutated_message, delay, repeat = self.byzz_mutator.mutate(message, method)
                
                # logger.error(f"mutation res: {mutated_message}, delay: {delay}, repeat: {repeat}") if method != "do_nothing" else None
                return handle_mutated_message(mutated_message, delay, repeat)
            else:
                # logger.debug(f"[OtherMessage] type={message_type}, delay={configed_delay}ms")
                return packet.data, configed_delay, 1
        return packet.data, configed_delay, 1

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
            parsed = PacketEncoderDecoder.decode_validation(message)
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
            signing_pub_hex = normalize_pubhex(signing_pub)

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

            parsed_signed = PacketEncoderDecoder.decode_validation(signed_message)
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
