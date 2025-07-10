import random
import threading
import time
import hashlib
from queue import Queue
from typing import Tuple
from loguru import logger

from protos import packet_pb2
from rocket_controller.strategies.strategy import Strategy
from rocket_controller.strategies.byzzql_agent import ByzzQLAgent
from rocket_controller.encoder_decoder import PacketEncoderDecoder
from rocket_controller.iteration_type import LedgerBasedIteration

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
        
        self.dispatch_interval = float(self.params.get("dispatch_interval_ms", 100)) / 1000.0
        self.dispatch_thread = threading.Thread(target=self.dispatch_loop, daemon=True)
        
        # Initialize RL agent
        self.rl_agent = ByzzQLAgent(
            action_space=["DROP", "MUTATE", "DELIVER"]
        )

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
        
        # todo: only process certain message types: TMValildation, TMTransaction, TMProposal
        message, message_type_no = PacketEncoderDecoder.decode_packet(packet)
        if message_type_no not in set(range(30, 36)).union({41}):
            return packet.data, 0, 1

        event = threading.Event()
        start_time = time.time()

        self.message_queue.put((packet.data, event))
        queue_size = self.message_queue.qsize()
        logger.debug(f"Queued packet from {packet.from_port} to {packet.to_port}, queue size: {queue_size}")
        event.wait()
        
        end_time = time.time()
        delay_ms = (end_time - start_time) * 1000
        
        logger.debug(f"Resumed packet from {packet.from_port} to {packet.to_port} after {delay_ms:.1f}ms delay")
        return packet.data, 0, 1

    def dispatch_loop(self):
        while self.running:
            try:
                # 1. Get message and apply collection delay
                msg, event = self.message_queue.get(timeout=1.0)
                time.sleep(self.dispatch_interval) # fixed delay to ensure queue contains messages

                # 2. Now we have a collection window - make RL decision
                current_state = self.get_inbox_state_hash()
                action = self.rl_agent.choose_action(current_state)
                
                # 3. Apply RL action (additional processing based on state)
                self.apply_rl_action(action, msg, event)

                # 4. Update RL learning
                #reward = self.calculate_reward()
                #next_state = self.get_inbox_state_hash()
                #self.rl_agent.update_q_value(current_state, action, reward, next_state)

            except:
                continue

    def get_inbox_state_hash(self):
        """
        For Inbox State Abstraction, we sort, concatenate and hash these serialized
        messages currently queued for processing at each replica.
        """
        queue_contents = list(self.message_queue.queue)
        serialized_messages = [item[0] for item in queue_contents]
        sorted_messages = sorted(serialized_messages)
        concatenated = b"".join(sorted_messages)
        return hashlib.sha256(concatenated).hexdigest()

    def apply_rl_action(self, action, msg, event):
        if action == "DROP":
            # ...
            # todo: dropping logic
            event.set()
        elif action == "MUTATE":
            # ...
            # todo: mutation logic, same mutation logic (mutation table) as in ByzzFuzzStrategy
            event.set()
        else:
            event.set()  # default: deliver

    def stop(self):
        self.running = False
        self.dispatch_thread.join()