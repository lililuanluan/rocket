"""This module contains the class that implements a random fuzzer."""

import random
from typing import Tuple

from xrpl_controller.strategy import Strategy


MAX_U32 = 2**32 - 1


class RandomFuzzer(Strategy):
    """Class that implements random fuzzer."""

    def __init__(
        self,
        drop_probability: float,
        send_probability: float,
        delay_probability: float,
        min_delay_ms: int,
        max_delay_ms: int,
    ):
        """
        Initializes the random fuzzer.

        Args:
            drop_probability: percent of packages that will be dropped.
            send_probability: percent of packages that will be sent immediately.
            delay_probability: percent of packages that will be delayed.
            min_delay_ms: minimum number of milliseconds that will be delayed.
            max_delay_ms: maximum number of milliseconds that will be delayed.
        """
        if (drop_probability + send_probability + delay_probability) != 1:
            raise ValueError("All probabilities added must be equal to 1.")

        self.drop_probability = drop_probability
        self.send_probability = send_probability
        self.delay_probability = delay_probability
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
