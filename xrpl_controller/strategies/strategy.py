"""This module is responsible for defining the Strategy interface."""

import threading
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Dict, List, Tuple

import base58
from loguru import logger

from protos import packet_pb2, ripple_pb2
from xrpl_controller.core import MAX_U32, flatten
from xrpl_controller.interceptor_manager import InterceptorManager
from xrpl_controller.validator_node_info import ValidatorNode


class IterationType:
    """Base class for defining iteration mechanisms."""

    def __init__(self):
        """Init Iteration Type with an InterceptorManager attached."""
        self._interceptor_manager = InterceptorManager()

    def init_interceptor(self):
        """Wrapper method to start the interceptor for the first time (on program initialization)."""
        self._interceptor_manager.start_new()


class TimeBasedIteration(IterationType):
    """Time based iteration type, restarts the interceptor process after a certain amount of seconds."""

    def __init__(self, timer_seconds: int):
        """
        Init TimeBasedIteration with an InterceptorManager attached.

        Args:
            timer_seconds: the amount of seconds an iteration should take.
        """
        super().__init__()
        self._timer_seconds = timer_seconds

    def start_timer(self):
        """Starts a thread which restarts the interceptor process after a set amount of seconds."""
        timer = threading.Timer(self._timer_seconds, self._interceptor_manager.restart)
        timer.start()


class LedgerBasedIteration(IterationType):
    """Ledger based iteration type, restarts the interceptor process after a certain amount of validated ledgers."""

    def __init__(self, max_ledger_seq: int):
        """
        Init LedgerBasedIteration with an InterceptorManager attached.

        Args:
            max_ledger_seq: The amount of ledgers to be validated in a single iteration.
        """
        super().__init__()

        self.prev_network_event = 0
        self.network_event_changes = 0
        self.ledger_seq = 0
        self.prev_validation_time = datetime.now()
        self.validation_time = timedelta()

        self._max_ledger_seq = max_ledger_seq

    def reset_values(self):
        """Reset state variables, called when interceptor is restarted."""
        self.prev_network_event = 0
        self.network_event_changes = 0
        self.ledger_seq = 0
        self.prev_validation_time = datetime.now()
        self.validation_time = timedelta()

    def update_iteration(self, status: ripple_pb2.TMStatusChange):
        """
        Update the iteration values, called when a TMStatusChange is received.

        Args:
            status: The TMStatusChange message received on the network.
        """
        if self.prev_network_event != status.newEvent:
            self.prev_network_event = status.newEvent
            self.network_event_changes += 1
            if status.ledgerSeq > self.ledger_seq:
                self.validation_time = datetime.now() - self.prev_validation_time
                self.ledger_seq = status.ledgerSeq
                self.prev_validation_time = datetime.now()
                logger.info(
                    f"Ledger {self.ledger_seq} validated, time elapsed: {self.validation_time}"
                )
            if self.ledger_seq == self._max_ledger_seq:
                self._interceptor_manager.restart()
                self.reset_values()


class Strategy(ABC):
    """Class that defines the Strategy interface."""

    def __init__(
        self,
        auto_partition: bool = True,
        keep_action_log: bool = True,
        iteration_type: IterationType | None = None,
    ):
        """
        Initialize the Strategy interface with needed attributes.

        Args:
            auto_partition (bool, optional): Whether the strategy will auto-apply network partitions. Defaults to True.
            keep_action_log (bool, optional): Whether the strategy will keep an action log. Defaults to True.
            iteration_type (IterationType, optional): Type of iteration logic to use.
        """
        self.validator_node_list: List[ValidatorNode] = []
        self.public_to_private_key_map: Dict[str, str] = {}
        self.node_amount: int = 0
        self.network_partitions: list[list[int]] = []
        self.port_dict: Dict[int, int] = {}
        self.communication_matrix: list[list[bool]] = []
        self.auto_partition = auto_partition
        self.keep_action_log = keep_action_log
        self.iteration_type = (
            LedgerBasedIteration(5) if iteration_type is None else iteration_type
        )

    def partition_network(self, partitions: list[list[int]]):
        """
        Set the network partition and update the communication matrix.

        Args:
            partitions (list[list[int]]): List containing the network partitions (as lists of port numbers).

        Raises:
            ValueError: if given partitions are invalid
        """
        flattened_partitions = flatten(partitions)
        if (
            set(flattened_partitions) != set(flatten(self.network_partitions))
            or len(flattened_partitions) != self.node_amount
        ):
            raise ValueError(
                "The given network partition is not valid for the current network."
            )

        self.network_partitions = partitions
        self.communication_matrix = [
            [False for _ in range(self.node_amount)] for _ in range(self.node_amount)
        ]

        for partition in partitions:
            for i in range(len(partition)):
                for j in range(i + 1, len(partition)):
                    self.communication_matrix[self.port_dict[partition[i]]][
                        self.port_dict[partition[j]]
                    ] = True
                    self.communication_matrix[self.port_dict[partition[j]]][
                        self.port_dict[partition[i]]
                    ] = True

    def apply_network_partition(
        self, action: int, peer_from_port: int, peer_to_port: int
    ) -> int:
        """
        Apply the network partition to an action with its related ports.

        Args:
            action (int): The action to apply the network partition on.
            peer_from_port (int): The peer port from where the message was sent.
            peer_to_port (int): The peer port to where the message was sent.

        Returns:
            int: An action represented as integer which is either the original action
            or the integer value representing the 'drop' action

        Raises:
            ValueError: If peer_from_port is equal to peer_to_port
        """
        if peer_from_port == peer_to_port:
            raise ValueError(
                "Sending port should not be the same as receiving port. "
                f"from_port == to_port == {peer_from_port}"
            )

        return (
            action
            if self.communication_matrix[self.port_dict[peer_from_port]][
                self.port_dict[peer_to_port]
            ]
            else MAX_U32
        )

    def update_network(self, validator_node_list: List[ValidatorNode]):
        """
        Update the strategy's attributes.

        Args:
            validator_node_list (list[ValidatorNode]): The list with (new) validator node information
        """
        logger.info("Updating the strategy's network information")
        self.validator_node_list = validator_node_list
        self.public_to_private_key_map.clear()
        self.node_amount = len(validator_node_list)

        self.network_partitions = [[node.peer.port for node in validator_node_list]]
        self.port_dict = {
            port: index for index, port in enumerate(self.network_partitions[0])
        }
        self.communication_matrix = [
            [True for _ in range(self.node_amount)] for _ in range(self.node_amount)
        ]

        for node in self.validator_node_list:
            decoded_pub_key = base58.b58decode(
                node.validator_key_data.validation_public_key,
                alphabet=base58.XRP_ALPHABET,
            )[1:34]
            decoded_priv_key = base58.b58decode(
                node.validator_key_data.validation_private_key,
                alphabet=base58.XRP_ALPHABET,
            )[1:33]
            self.public_to_private_key_map[decoded_pub_key.hex()] = (
                decoded_priv_key.hex()
            )

        if isinstance(self.iteration_type, TimeBasedIteration):
            self.iteration_type.start_timer()

    def update_status(self, status: ripple_pb2.TMStatusChange):
        """Update the strategy's state variables, when a new TMStatusChange is received."""
        if isinstance(self.iteration_type, LedgerBasedIteration):
            self.iteration_type.update_iteration(status)

    @abstractmethod
    def handle_packet(
        self, packet: packet_pb2.Packet
    ) -> Tuple[bytes, int]:  # pragma: no cover
        """
        This method is responsible for returning a possibly mutated packet and an action.

        Args:
            packet: the original packet.

        Returns:
            Tuple[bytes, int]: the new packet and the action.
        """
        pass
