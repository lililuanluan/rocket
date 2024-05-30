"""This module contains the class that implements a random fuzzer."""

import random
from typing import Tuple

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
    ):
        """
        Initializes the random fuzzer.

        Args:
            drop_probability: percent of packages that will be dropped.
            delay_probability: percent of packages that will be delayed.
            min_delay_ms: minimum number of milliseconds that will be delayed.
            max_delay_ms: maximum number of milliseconds that will be delayed.
            seed: seed for random number generator. Defaults to -sys.maxsize to indicate no seeding.

        Raises:
            ValueError: if the given probabilities or delays are invalid
        """
        super().__init__()

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

    def handle_packet(self, packet: bytes) -> Tuple[bytes, int]:
        """
        Implements the handle_packet method with a random action.

        Args:
            packet: the original packet to be sent.

        Returns:
            Tuple[bytes, int]: the new packet and the random action.
        """
        choice: float = random.random()
        if choice < self.send_probability:
            return packet, 0
        elif choice < self.send_probability + self.drop_probability:
            return packet, MAX_U32
        else:
            return packet, random.randint(self.min_delay_ms, self.max_delay_ms)
