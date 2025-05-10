import random
import threading
import time
from queue import PriorityQueue
from typing import Tuple

from protos import packet_pb2
from rocket_controller.helper import MAX_U32
from rocket_controller.strategies.strategy import Strategy

class RandomPriority(Strategy):
    def __init__(
        self,
        network_config_path: str | None = None,
        strategy_config_path: str | None = None,
        auto_partition: bool = True,
        auto_parse_identical: bool = True,
        auto_parse_subsets: bool = True,
        keep_action_log: bool = True,
        iteration_type=None,
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
            network_overrides,
            strategy_overrides,
        )

    def setup(self):
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
        self.max_events = int(self.params.get("max_events", 100)) # figure this out
        self.r = self.max_events / 2
        
        self.dispatch_thread = threading.Thread(target=self.dispatch_loop, daemon=True)
        self.dispatch_thread.start()


    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int, int]:
        event = threading.Event()

        with self.lock:
            priority = random.randint(0, 100)
            self.counter += 1
            self.queue.put((priority, self.counter, event))
            # print(f"[handle_packet] Queued packet from {packet.from_port} to {packet.to_port} with priority {priority}")

        # For the threading test -> numbers should be printed in a nondeterministic order
        # curr_count = self.counter
        # print(curr_count)
        # time.sleep(random.randint(1, 3))  # Wait random amount of time
        # print(curr_count)

        event.wait()
        # print(f"[handle_packet] Resumed packet from {packet.from_port} to {packet.to_port}")
        return packet.data, 0, 1

    def dispatch_loop(self):
        while self.running:
            with self.lock:
                inbox_size = self.queue.qsize()
                # Adjust rate r based on inbox size
                if inbox_size > self.target_inbox * self.overflow_factor:
                    self.r = min(self.r * self.sensitivity_ratio, self.max_events)
                elif inbox_size < self.target_inbox * self.underflow_factor:
                    self.r = max(self.r / self.sensitivity_ratio, self.max_events / 6)
                # else: r stays the same

                packets_per_sec = max(1, int(self.r))
                interval = 1.0 / packets_per_sec

                if not self.queue.empty():
                    priority, count, event = self.queue.get()
                    # print(f"[dispatch_loop] Dispatching event with priority {priority}, tie-breaker {count}")
                    event.set()

            time.sleep(interval)

    def stop(self):
        self.running = False
        self.dispatch_thread.join()
