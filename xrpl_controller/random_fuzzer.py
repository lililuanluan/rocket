"""This module contains the class that implements a random fuzzer."""

import random
from typing import Tuple

from xrpl_controller.strategy import Strategy


MAX_U32 = 2**32 - 1


class RandomFuzzer(Strategy):
    """Class that implements random fuzzer."""

    def handle_packet(self, packet: bytes) -> Tuple[bytes, int]:
        """
        Implements the handle_packet method with a random action.

        Args:
            packet: the original packet to be sent.

        Returns:
        Tuple[bytes, int]: the new packet and the random action.
        """
        choice: float = random.random()
        if choice < 0.95:
            return packet, 0
        elif choice < 0.96:
            return packet, MAX_U32
        else:
            return packet, random.randint(1, 150)
