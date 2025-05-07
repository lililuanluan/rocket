import random
import threading
import time
from queue import PriorityQueue
from typing import Tuple

from protos import packet_pb2
from rocket_controller.helper import MAX_U32
from rocket_controller.strategies.strategy import Strategy

class RandomPriorityScheduler(Strategy):
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
        self.dispatch_thread = threading.Thread(target=self.dispatch_loop, daemon=True)
        self.dispatch_interval_ms = int(self.params.get("dispatch_interval_ms", 1))
        self.dispatch_thread.start()

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int, int]:
        event = threading.Event()

        with self.lock:
            priority = random.randint(0, 100)
            self.counter += 1
            self.queue.put((priority, self.counter, event))

        # For the threading test -> numbers should be printed in a nondeterministic order
        # curr_count = self.counter
        # print(curr_count)
        # time.sleep(random.randint(1, 3))  # Wait random amount of time
        # print(curr_count)

        event.wait()
        return packet.data, 0, 1

    def dispatch_loop(self):
        while self.running:
            with self.lock:
                if not self.queue.empty():
                    _, _, event = self.queue.get()
                    event.set()
            time.sleep(self.dispatch_interval_ms / 1000.0)

    def stop(self):
        self.running = False
        self.dispatch_thread.join()
