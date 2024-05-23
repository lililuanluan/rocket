"""This module is responsible for defining the Strategy interface."""

from abc import ABC, abstractmethod
from typing import Tuple


class Strategy(ABC):
    """Class that defines the Strategy interface."""

    @abstractmethod
    def handle_packet(self, packet: bytes) -> Tuple[bytes, int]:
        """
        This method is responsible for returning a possibly mutated packet and an action.

        Args:
            packet: the original packet.

        Returns:
        Tuple[bytes, int]: the new packet and the action.
            action 0: send immediately without delay
            action MAX: drop the packet
            action 0<x<MAX: delay the packet x ms
        """
        pass
