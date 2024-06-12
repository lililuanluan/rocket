"""This module contains the class that implements a random fuzzer."""

import random
from typing import Tuple

from xrpl_controller.core import MAX_U32
from xrpl_controller.strategies.strategy import Strategy


class RandomFuzzer(Strategy):
    """Class that implements random fuzzer."""

    def __init__(
        self,
        config_file: str = None,
    ):
        """
        Initializes the random fuzzer.

        Raises:
            ValueError: if retrieved probabilities or delays are invalid
        """
        super().__init__(config_file=config_file)

        if self.params['seed'] is not None:
            random.seed(self.params['seed'])

        if self.params['drop_probability'] < 0 or self.params['delay_probability'] < 0:
            raise ValueError(
                f"drop and delay probabilities must be non-negative, drop_probability: {self.params['drop_probability']}, delay_probability: {self.params['delay_probability']}"
            )

        if (self.params['drop_probability'] + self.params['delay_probability']) > 1.0:
            raise ValueError(
                f"drop and delay probabilities must sum to less than or equal to 1.0, but was \
                {self.params['drop_probability'] + self.params['delay_probability']}"
            )

        if self.params['min_delay_ms'] < 0 or self.params['max_delay_ms'] < 0:
            raise ValueError(
                f"delay values must both be non-negative, min_delay_ms: {self.params['min_delay_ms']}, max_delay_ms: {self.params['max_delay_ms']}"
            )

        if self.params['min_delay_ms'] > self.params['max_delay_ms']:
            raise ValueError(
                f"min_delay_ms must be smaller or equal to max_delay_ms, min_delay_ms: {self.params['min_delay_ms']}, \
                max_delay_ms: {self.params['max_delay_ms']}"
            )

        self.params['send_probability'] = 1 - self.params['drop_probability'] - self.params['delay_probability']

    def handle_packet(self, packet: bytes) -> Tuple[bytes, int]:
        """
        Implements the handle_packet method with a random action.

        Args:
            packet: the original packet to be sent.

        Returns:
            Tuple[bytes, int]: the new packet and the random action.
        """
        choice: float = random.random()
        if choice < self.params['send_probability']:
            return packet, 0
        elif choice < self.params['send_probability'] + self.params['drop_probability']:
            return packet, MAX_U32
        else:
            return packet, random.randint(self.params['min_delay_ms'], self.params['max_delay_ms'])
