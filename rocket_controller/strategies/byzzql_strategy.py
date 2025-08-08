import random
import sys
import threading
import time
import hashlib
from queue import Queue
from typing import Tuple
from loguru import logger
from xrpl.clients import JsonRpcClient

from protos import packet_pb2, ripple_pb2
from rocket_controller.strategies.strategy import Strategy
from rocket_controller.strategies.byzzql_agent import ByzzQLAgent
from rocket_controller.encoder_decoder import (
    DecodingNotSupportedError,
    PacketEncoderDecoder,
)
from rocket_controller.iteration_type import LedgerBasedIteration
from rocket_controller.helper import MAX_U32
from xrpl.core.binarycodec import decode

# TODO: check how we learn from the RL agent, how often we update the Q-values. Are most values 0.0 or not?

class ByzzQLStrategy(Strategy):
    def __init__(
        self,
        network_config_path: str | None = None,
        strategy_config_path: str | None = None,
        auto_partition: bool = True,
        auto_parse_identical: bool = True,
        auto_parse_subsets: bool = True,
        keep_action_log: bool = True,
        iteration_type = LedgerBasedIteration(10, 10, 65),
        log_dir: str | None = None,
        network_overrides=None,
        strategy_overrides=None,
    ):
        super().__init__(
            network_config_path,
            strategy_config_path,
            auto_partition,
            auto_parse_identical,
            auto_parse_subsets,
            keep_action_log,
            iteration_type,
            log_dir,
            network_overrides,
            strategy_overrides,
        )

        self.message_queue = Queue()
        self.running = True

        # Fields for dynamic rate
        self.sensitivity_ratio = float(self.params.get("sensitivity_ratio", 1.2))
        self.target_inbox = int(self.params.get("target_inbox", 30))
        self.overflow_factor = float(self.params.get("overflow_factor", 1.2))
        self.underflow_factor = float(self.params.get("underflow_factor", 0.8))
        self.max_events = int(self.params.get("max_events", 300))  # figure this out
        self.r = self.max_events / 2

        # Uncomment to silence the debug printouts
        # logger.remove()
        # logger.add(sys.stderr, level="INFO")  # or "WARNING" to silence info logs too

        self.dispatch_thread = threading.Thread(target=self.dispatch_loop, daemon=True)
        self.clients = {}

        # Initialize RL agent
        self.rl_agent = ByzzQLAgent(
            action_space=["DROP", "MUTATE", "DELIVER"]
        )
        
        # initialize process faults (mutations)
        self.iteration_type.register_callback(self.init_faults)

        self.old_proposals = []
        self.old_validations = []
    
    def init_faults(self) -> None:
        self.process_faults_list = []
        
        # for each round generate a random seed and use it for mutating messages,
        # this ensures that mutations are deterministic for each test run
        for i in range(1, self.iteration_type._max_ledger_seq + 1):
            seed = random.randint(0, 1000000)
            self.process_faults_list.append((i, seed))

        logger.debug("Process faults (rounds and seeds):")
        for round_num, seed in self.process_faults_list:
            logger.debug(f"Round {round_num}:, {seed}")

    def setup(self):
        if self.dispatch_thread.is_alive():
            logger.info("Joining dispatch thread")
            self.running = False
            self.dispatch_thread.join()
            logger.info("Dispatch thread joined")
        self.running = True
        self.dispatch_thread = threading.Thread(target=self.dispatch_loop, daemon=True)
        self.dispatch_thread.start()

        for peer_id in range(self.network.node_amount):
            validator = self.network.validator_node_list[peer_id]
            rpc_address = f"http://{validator.rpc.as_url()}/"
            self.clients[peer_id] = JsonRpcClient(rpc_address)

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int, int]:
        """Store message in queue and wait for dispatch"""
        
        try:
            message, message_type_no = PacketEncoderDecoder.decode_packet(packet)
        except DecodingNotSupportedError:
            logger.error(
                f"Decoding of message is not supported"	)
            return packet.data, 0, 1
    
        self.save_packet_for_mutation(message)
        
        # only process certain message types: TMValildation, TMProposeSet, TMTransaction
        if not (isinstance(message, ripple_pb2.TMValidation) or
                isinstance(message, ripple_pb2.TMProposeSet) or
                isinstance(message, ripple_pb2.TMTransaction)):
            return packet.data, 0, 1

        extracted_value = None
        if isinstance(message, ripple_pb2.TMProposeSet):
            extracted_value = f"ProposeSet:{packet.from_port}:{packet.to_port}:{message.proposeSeq}:{message.currentTxHash.hex()}"
        elif isinstance(message, ripple_pb2.TMValidation):
            # We should use transactions here to extract values.
            ledger_hash, transactions, validated, ledger_index = self.network.get_transactions('closed', self.network.port_to_id(packet.from_port))
            extracted_value = f"Validation:{packet.from_port}:{packet.to_port}:{message.validation.hex()}"
        elif isinstance(message, ripple_pb2.TMTransaction):
            decoded = decode(message.rawTransaction.hex())
            # Decoded TMTransaction: {'TransactionType': 'Payment', 'Flags': 0, 'Sequence': 2, 'LastLedgerSequence': 25, 'Amount': '100001000000', 'Fee': '10', 'SigningPubKey': '0330E7FC9D56BB25D6893BA3F317AE5BCF33B3291BD63DB32654A313222F7FD020', 'TxnSignature': '304402200BC25C59B3B22D01B9563D5CF0AB3ECD16B158916D885C26A60DA98CAE35757402207DEA9F34944AA7FAB26C8CC13FB9CD18A2F73EAF556CDEC6CCD0E216F4160A3D', 'Account': 'rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh', 'Destination': 'rMAyDK9H3z3CM6YhTcdGCYUC2RGcDtaGCY'}
            extracted_value = f"Transaction:{packet.from_port}:{packet.to_port}:{decoded['TransactionType']}:{decoded['Sequence']}:{decoded['Amount']}"

        event = threading.Event()
        start_time = time.time()
        result_container = [packet.data, 0, 1]  # default: deliver

        self.message_queue.put((packet, event, extracted_value, result_container))
        queue_size = self.message_queue.qsize()
        logger.debug(f"Queued packet from {packet.from_port} to {packet.to_port}, queue size: {queue_size}")
        event.wait()
        
        end_time = time.time()
        delay_ms = (end_time - start_time) * 1000
        
        logger.debug(f"Resumed packet from {packet.from_port} to {packet.to_port} after {delay_ms:.1f}ms delay")
        return result_container[0], result_container[1], result_container[2]

    def dispatch_loop(self):
        while self.running:
            try:
                # 1. Get message and apply collection delay
                packet, event, extracted_value, result_container = self.message_queue.get(timeout=1.0)

                # Following code inspired by PriorityStrategy, with some small changes.
                # Applies a dynamic dispatch rate as defined in http://doi.org/10.1109/ICSE-SEIP58684.2023.00009
                inbox_size = self.message_queue.qsize()

                # Adjust rate r based on inbox size
                if inbox_size > self.target_inbox * self.overflow_factor:
                    self.r = min(self.r * self.sensitivity_ratio, inbox_size)
                elif inbox_size < self.target_inbox * self.underflow_factor:
                    self.r = max(self.r / self.sensitivity_ratio, inbox_size / 6)
                # else: r doesn't change

                # Rate is clamped |events|/6 <= r <= |events|
                self.r = int(max(inbox_size / 6, min(self.r, inbox_size)))

                logger.debug(f"RATE {self.r}")

                # Only apply rate if r is not zero
                if self.r > 0:
                    interval = 1.0 / self.r
                    time.sleep(interval)

                # 2. Now we have a collection window - make RL decision
                current_state = self.get_inbox_state_hash()
                action = self.rl_agent.choose_action(current_state)

                # 3. Apply RL action (additional processing based on state)
                self.apply_rl_action(action, packet, event, result_container)

                # 4. Update RL learning
                next_state = self.get_inbox_state_hash()
                self.rl_agent.update_q_value(current_state, action, next_state)
            except:
                continue

    def get_inbox_state_hash(self):
        """
        For Inbox State Abstraction, use extracted key fields instead of just hashing the raw serialized
        data to get a more meaningful state representation:
        - TMProposeSet: proposeSeq, currentTxHash
        - TMValidation: validation
        - TMTransaction: rawTransaction
        We sort, concatenate  and hash these extracted values from messages currently queued for
        processing at each replica.
        """
        queue_contents = list(self.message_queue.queue)
        extracted_values = [item[2] for item in queue_contents if item[2] is not None]
        sorted_values = sorted(extracted_values)
        concatenated = "|".join(sorted_values)
        return hashlib.sha256(concatenated.encode()).hexdigest()

    def apply_rl_action(self, action, packet, event, result_container):
        peer_from_id = self.network.port_to_id(packet.from_port)
        peer_to_id = self.network.port_to_id(packet.to_port)
        if action == "DROP":
            result_container[0] = packet.data 
            result_container[1] = MAX_U32 
            result_container[2] = 1
            logger.debug(f"RL Action: DROP - packet from {peer_from_id} to {peer_to_id} will be dropped.")
            event.set()
        elif action == "MUTATE":
            if peer_from_id in self.iteration_type._byzantine_nodes:
                # mutation logic
                for round_num, seed in self.process_faults_list:
                    if round_num == self.get_current_round_of_node(peer_from_id):
                        logger.debug(f"RL Action: MUTATE - packet from {peer_from_id} to {peer_to_id}, round: {self.get_current_round_of_node(peer_from_id)}.")
                        mutated_data, delay, action_type = self.corrupt_message(packet, seed)
                        result_container[0] = mutated_data
                        result_container[1] = delay
                        result_container[2] = action_type
                        event.set()
                        return
            event.set() # else just deliver the message
            # TODO: it could happen that RL agent chooses action "mutate" and then we actually just deliver the message
            # because the node is not byzantine, then in Q table we still store that action as "mutate". 
            # We can either store it as "deliver"or we can have two separate action spaces (one with MUTATE other without)
            # but then when choosing best action to take we would have to ignore MUTATE sometimes. Would this still be valid RL?
        else:  
            event.set() # default: deliver

    def stop(self):
        self.running = False
        self.dispatch_thread.join()
        
    def save_packet_for_mutation(self, message) -> None:
        if isinstance(message, ripple_pb2.TMProposeSet):
            self.old_proposals.append(message.currentTxHash)
        elif isinstance(message, ripple_pb2.TMValidation):
            self.old_validations.append(message.validation)

    def get_current_round_of_node(self, node_id: int) -> int:
        """Get the current round (ledger sequence) of a specific node."""
        for _node_id, entry in self.iteration_type.ledger_validation_map.items():
            if node_id == _node_id:
                return entry["seq"]
        return -1
    
    def corrupt_message(self, packet: packet_pb2.Packet, seed: int) -> tuple[bytes, int, int]:
        try:
            message, message_type_no = PacketEncoderDecoder.decode_packet(packet)
        except DecodingNotSupportedError:
            logger.error(f"Decoding of message not supported")
            return packet.data, 0, 1

        if isinstance(message, ripple_pb2.TMProposeSet):
            return self._corrupt_TMProposeSet(message, message_type_no, seed)
        elif isinstance(message, ripple_pb2.TMValidation):
            return self._corrupt_TMValidation(message, message_type_no, seed)
        elif isinstance(message, ripple_pb2.TMTransaction):
            return self._corrupt_TMTransaction(message, message_type_no, seed)
        
        return packet.data, 0, 1

    def _corrupt_TMProposeSet(self, message, message_type_no: int, seed: int) -> tuple[bytes, int, int]:
        rng = random.Random(seed)
        if rng.choice([True, False]):  
            logger.debug(f"Corrupting proposeSeq: {message.proposeSeq}")
            message.proposeSeq += rng.choice([-1, 1])
            logger.debug(f"New proposeSeq: {message.proposeSeq}")
        else:
            logger.debug(f"Corrupting currentTxHash: {message.currentTxHash.hex()}")
            message.currentTxHash = rng.choice(self.old_proposals)
            logger.debug(f"New currentTxHash: {message.currentTxHash.hex()}")

        signed_message = PacketEncoderDecoder.sign_message(
            message, self.network.public_to_private_key_map[message.nodePubKey.hex()]
        )
        return PacketEncoderDecoder.encode_message(signed_message, message_type_no), 0, 1

    def _corrupt_TMValidation(self, message, message_type_no: int, seed: int) -> tuple[bytes, int, int]:
        rng = random.Random(seed)
        logger.debug(f"Corrupting TMValidation: {message.validation.hex()}")
        message.validation = rng.choice(self.old_validations)
        logger.debug(f"New TMValidation: {message.validation.hex()}")
        return PacketEncoderDecoder.encode_message(message, message_type_no), 0, 1

    def _corrupt_TMTransaction(self, message, message_type_no: int, seed: int) -> tuple[bytes, int, int]:
        rng = random.Random(seed)
        logger.debug(f"Corrupting TMTransaction message which was {message.rawTransaction.hex()}")
        transaction_hash_set = [tx[3] for tx in self.iteration_type.to_be_validated_txs] 
        message.rawTransaction = self.iteration_type.reverse_compute_tx_hash(rng.choice(transaction_hash_set))
        logger.debug(f"New TMTransaction message is {message.rawTransaction.hex()}")
        return PacketEncoderDecoder.encode_message(message, message_type_no), 0, 1