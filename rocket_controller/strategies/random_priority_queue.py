"""This module contains the class that implements a random priority queue."""

import random
from typing import Any, Dict, Tuple

from protos import packet_pb2
from rocket_controller.helper import MAX_U32
from rocket_controller.iteration_type import TimeBasedIteration, LedgerBasedIteration
from rocket_controller.strategies.strategy import Strategy


class RandomPriorityQueue(Strategy):
    """Class that implements a random fuzzer."""

    def __init__(
        self,
        network_config_path: str = "./config/network/default_network.yaml",
        strategy_config_path: str | None = None,
        auto_parse_identical: bool = True,
        auto_parse_subsets: bool = True,
        iteration_type: TimeBasedIteration | None = LedgerBasedIteration(10, 10, 60),
        network_overrides: Dict[str, Any] | None = None,
        strategy_overrides: Dict[str, Any] | None = None,
    ):
        """
        Initializes the random priority queue.

        Args:
            network_config_path: The path to a network config file to be used.
            strategy_config_path: The path to a strategy config file to be used.
            auto_parse_identical: Whether to auto-parse identical packages per peer combination.
            auto_parse_subsets: Whether to auto-parse identical packages w.r.t. defined subsets.
            iteration_type: The type of iteration to keep track of.
            network_overrides: A dictionary containing parameter names and values which override the network config.
            strategy_overrides: A dictionary containing parameter names and values which override the strategy config.

        Raises:
            ValueError: If retrieved probabilities or delays are invalid.
        """
        super().__init__(
            network_config_path=network_config_path,
            strategy_config_path=strategy_config_path,
            auto_parse_identical=auto_parse_identical,
            auto_parse_subsets=auto_parse_subsets,
            iteration_type=iteration_type,
            network_overrides=network_overrides,
            strategy_overrides=strategy_overrides,
        )

        if self.params["seed"] is not None:
            random.seed(self.params["seed"])



    def setup(self):
        """Setup method for RandomFuzzer."""

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int, int]:
        """
        Implements the handle_packet method with a random action.

        Args:
            packet: The original packet to be sent.

        Returns:
            Tuple[bytes, int, int]: The new packet, the random action and the send amount.
        """
        choice: float = random.random()
        if choice < self.params["send_probability"]:
            return packet.data, 0, 1
        elif choice < self.params["send_probability"] + self.params["drop_probability"]:
            return packet.data, MAX_U32, 1
        else:
            return (
                packet.data,
                random.randint(
                    self.params["min_delay_ms"], self.params["max_delay_ms"]
                ),
                1,
            )
