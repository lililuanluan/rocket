"""This module contains the class that implements a random fuzzer."""

import random
from typing import Tuple

from protos import packet_pb2
from xrpl_controller.core import MAX_U32
from xrpl_controller.strategies.strategy import Strategy


class RandomFuzzer(Strategy):
    """Class that implements random fuzzer."""

    def __init__(
        self,
        drop_probability: float,
        delay_probability: float,
        min_delay_ms: int,
        max_delay_ms: int,
        seed: int | None = None,
        auto_parse_identical: bool = True,
        auto_parse_subsets: bool = True,
    ):
        """
        Initializes the random fuzzer.

        Args:
            drop_probability: percent of packages that will be dropped.
            delay_probability: percent of packages that will be delayed.
            min_delay_ms: minimum number of milliseconds that will be delayed.
            max_delay_ms: maximum number of milliseconds that will be delayed.
            seed: seed for random number generator. Defaults to -sys.maxsize to indicate no seeding.
            auto_parse_identical: whether to auto-parse identical packages per peer combination.
            auto_parse_subsets: whether to auto-parse identical packages w.r.t. defined subsets

        Raises:
            ValueError: if the given probabilities or delays are invalid
        """
        super().__init__(auto_parse_identical=auto_parse_identical, auto_parse_subsets=auto_parse_subsets)

        if seed is not None:
            random.seed(seed)

        if drop_probability < 0 or delay_probability < 0:
            raise ValueError(
                f"drop and delay probabilities must be non-negative, drop_probability: {drop_probability}, \
                delay_probability: {delay_probability}"
            )

        if (drop_probability + delay_probability) > 1.0:
            raise ValueError(
                f"drop and delay probabilities must sum to less than or equal to 1.0, but was \
                {drop_probability + delay_probability}"
            )

        if min_delay_ms < 0 or max_delay_ms < 0:
            raise ValueError(
                f"delay values must both be non-negative, min_delay_ms: {min_delay_ms}, max_delay_ms: {max_delay_ms}"
            )

        if min_delay_ms > max_delay_ms:
            raise ValueError(
                f"min_delay_ms must be smaller or equal to max_delay_ms, min_delay_ms: {min_delay_ms}, \
                max_delay_ms: {max_delay_ms}"
            )

        self.drop_probability = drop_probability
        self.delay_probability = delay_probability
        self.send_probability = 1 - drop_probability - delay_probability
        self.min_delay_ms = min_delay_ms
        self.max_delay_ms = max_delay_ms

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int]:
        """
        Implements the handle_packet method with a random action.

        Args:
            packet: the original packet to be sent.

        Returns:
            Tuple[bytes, int]: the new packet and the random action.
        """
        choice: float = random.random()
        if choice < self.send_probability:
            return packet.data, 0
        elif choice < self.send_probability + self.drop_probability:
            return packet.data, MAX_U32
        else:
            return packet.data, random.randint(self.min_delay_ms, self.max_delay_ms)
