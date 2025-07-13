import random
import threading
import time
import hashlib
from queue import Queue
from typing import Tuple
from loguru import logger
from protos import packet_pb2, ripple_pb2
from rocket_controller.strategies.strategy import Strategy
from rocket_controller.strategies.byzzql_agent import ByzzQLAgent
from rocket_controller.encoder_decoder import (
    DecodingNotSupportedError,
    PacketEncoderDecoder,
)
from rocket_controller.iteration_type import LedgerBasedIteration
from rocket_controller.helper import MAX_U32

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
        
        # TODO: tune dispatch interval, this is also related to todo in packet_server.py (max_workers)
        self.dispatch_interval = float(self.params.get("dispatch_interval_ms", 100)) / 1000.0
        self.dispatch_thread = threading.Thread(target=self.dispatch_loop, daemon=True)
        
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
            extracted_value = f"ProposeSet:{message.proposeSeq}:{message.currentTxHash.hex()}"
        elif isinstance(message, ripple_pb2.TMValidation):
            extracted_value = f"Validation:{message.validation.hex()}"
        elif isinstance(message, ripple_pb2.TMTransaction):
            extracted_value = f"Transaction:{message.rawTransaction.hex()}"

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
                time.sleep(self.dispatch_interval) # fixed delay to ensure queue contains messages

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