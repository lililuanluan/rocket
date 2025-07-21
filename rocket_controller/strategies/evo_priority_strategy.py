import random
import threading
import time
#from queue import PriorityQueue, ShutDown, Empty
from time import sleep
from typing import Tuple

from loguru import logger
from mypy.stubgen import EMPTY

from protos import packet_pb2
from rocket_controller.helper import MAX_U32
from rocket_controller.strategies.strategy import Strategy
from rocket_controller.encoder_decoder import (
    DecodingNotSupportedError,
    PacketEncoderDecoder,
)
from rocket_controller.iteration_type import LedgerBasedIteration, TimeBasedIteration

class EvoPriorityStrategy(Strategy):
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

        self.queue = PriorityQueue()
        self.counter = 0

        self.lock = threading.Lock()
        self.running = True

        self.min_priority = int(self.params.get("min_priority", 1))
        self.max_priority = int(self.params.get("max_priority", 100))
        # self.dispatch_interval_ms = int(self.params.get("dispatch_interval_ms", 20))

        self.sensitivity_ratio = float(self.params.get("sensitivity_ratio", 1.2))
        self.target_inbox = int(self.params.get("target_inbox", 10))
        self.overflow_factor = float(self.params.get("overflow_factor", 1.2))
        self.underflow_factor = float(self.params.get("underflow_factor", 0.8))
        self.max_events = int(self.params.get("max_events", 1000)) # figure this out
        self.min_packets_per_second = int(self.params.get("min_packets_per_second", 100))
        self.r = self.max_events / 2
        self.priorities = self.params.get("encoding")
        self.dispatch_thread = threading.Thread(target=self.dispatch_loop, daemon=True)


    def setup(self):
        if not self.priorities:
            self.priorities = [random.randint(self.min_priority, self.max_priority) for _ in range(7 * self.network.node_amount * (self.network.node_amount - 1))]
            logger.info(f"Priorities not specified, using random: {self.priorities}")

        if len(self.priorities) != 7 * self.network.node_amount * (self.network.node_amount - 1):
            raise ValueError(f"Priorities must be of length {7 * self.network.node_amount * (self.network.node_amount - 1)}, but was {len(self.priorities)}")
        self.counter = 0

        self.queue.shutdown()
        self.queue = PriorityQueue()
        if self.dispatch_thread.is_alive():
            logger.info("Joining dispatch thread")
            self.dispatch_thread.join()
            logger.info("Dispatch thread joined")
        self.dispatch_thread = threading.Thread(target=self.dispatch_loop, daemon=True)
        self.dispatch_thread.start()



    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int, int]:
        message, message_type_no = PacketEncoderDecoder.decode_packet(packet)
        # return packet.data, 0, 1

        if message_type_no not in set(range(30, 36)).union({41}):
            return packet.data, 0, 1

            # To get type index -> subtract 30, for validation, subtract 35
        type_id = message_type_no - 30 if message_type_no != 41 else 6
        sender_node_id = self.network.port_to_id(packet.from_port)
        receiver_node_id = self.network.port_to_id(packet.to_port)

        index = (type_id * (self.network.node_amount * (self.network.node_amount - 1))
                 + sender_node_id * (self.network.node_amount - 1)
                 + (receiver_node_id if receiver_node_id < sender_node_id else receiver_node_id - 1))

        priority = self.priorities[index]
        count = 0
        with self.lock:
            count = self.counter
            self.counter += 1
        priority = priority + count
        entry_time = time.time() * 1000
        event = threading.Event()
        self.queue.put((priority, count, event))
        event.wait()
        exit_time = time.time() * 1000
        if exit_time - entry_time > 1000:
            logger.warning(f"It took {exit_time - entry_time} ms to process a packet")
            # print(f"[handle_packet] Queued packet from {packet.from_port} to {packet.to_port} with priority {priority}")

        # For the threading test -> numbers should be printed in a nondeterministic order
        # curr_count = self.counter
        # print(curr_count)
        # time.sleep(random.randint(1, 3))  # Wait random amount of time
        # print(curr_count)

        # print(f"[handle_packet] Resumed packet from {packet.from_port} to {packet.to_port}")
        return packet.data, 0, 1

    def dispatch_loop(self):
        while self.running:
            try:
                priority, count, event = self.queue.get()
                event.set()
            except ShutDown:
                logger.info("Shutting down dispatch thread")
                break
            inbox_size = self.queue.qsize()
            # Adjust rate r based on inbox size
            if inbox_size > self.target_inbox * self.overflow_factor:
                self.r = min(self.r * self.sensitivity_ratio, self.max_events)
            elif inbox_size < self.target_inbox * self.underflow_factor:
                self.r = max(self.r / self.sensitivity_ratio, self.max_events / 6)
            # else: r stays the same
            packets_per_sec = max(self.min_packets_per_second, int(self.r))
            interval = 1.0 / packets_per_sec

            # logger.info(f"Dispatching {packets_per_sec} packets per second, inbox size: {inbox_size}")

            time.sleep(interval)

    def stop(self):
        self.running = False
        self.dispatch_thread.join()

