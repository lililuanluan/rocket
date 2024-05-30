"""This module is responsible for defining the Strategy interface."""

from abc import ABC, abstractmethod
from typing import Dict, List, Tuple

from xrpl_controller.core import MAX_U32, flatten, validate_ports
from xrpl_controller.message_action import MessageAction
from xrpl_controller.validator_node_info import ValidatorNode


class Strategy(ABC):
    """Class that defines the Strategy interface."""

    def __init__(self, auto_partition: bool = True, auto_parse: bool = True):
        """
        Initialize the Strategy interface with needed fields.

        Args:
            auto_partition (bool, optional): Whether the strategy will auto-apply network partitions. Defaults to True.
            auto_parse (bool, optional): Whether the strategy will perform same actions on identical messages
        """
        self.validator_node_list: List[ValidatorNode] = []
        self.node_amount: int = 0
        self.network_partitions: list[list[int]] = []
        self.port_dict: Dict[int, int] = {}
        self.communication_matrix: list[list[bool]] = []
        self.message_action_matrix: list[list[MessageAction]] = []
        self.auto_partition = auto_partition
        self.auto_parse = auto_parse

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
                    idx_1 = self.idx(partition[i])
                    idx_2 = self.idx(partition[j])

                    self.communication_matrix[idx_1][idx_2] = True
                    self.communication_matrix[idx_2][idx_1] = True

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
        validate_ports(peer_from_port, peer_to_port)
        return (
            action
            if self.communication_matrix[self.port_dict[peer_from_port]][
                self.port_dict[peer_to_port]
            ]
            else MAX_U32
        )

    def set_message_action(
        self,
        peer_from_port: int,
        peer_to_port: int,
        initial_message: bytes,
        final_message: bytes,
        action: int,
    ):
        """
        Set an entry in the message_action_matrix.

        Args:
            peer_from_port: Sender peer port.
            peer_to_port: Receiving peer port.
            initial_message: The pre-processed message.
            final_message: The (possibly mutated) processed message
            action: The taken action
        """
        validate_ports(peer_from_port, peer_to_port)
        self.message_action_matrix[self.idx(peer_from_port)][
            self.idx(peer_to_port)
        ].set_initial_message(initial_message).set_final_message(
            final_message
        ).set_action(action)

    def parse_message(
        self, peer_from_port: int, peer_to_port: int, message: bytes
    ) -> tuple[bool, tuple[bytes, int]]:
        """
        Parse a message automatically to a final state with an action if it was matching to the previous message.

        Example Usage in Pseudocode: res = parse(port_1, port_2, message);
        if(res._1) then message = res._2._1; action = res._2._2; send(message, action)
        else (message, action) = handle(message); send(message, action)

        Args:
            peer_from_port: Sender peer port.
            peer_to_port: Receiving peer port.
            message: The message to be checked for parsing

        Returns:
            Tuple(bool, Tuple(bytes, int)): Boolean indicating success along with final message and action.
        """
        message_action = self.message_action_matrix[self.idx(peer_from_port)][
            self.idx(peer_to_port)
        ]
        return message == message_action.initial_message, (
            message_action.final_message,
            message_action.action,
        )

    def update_network(self, validator_node_list: List[ValidatorNode]):
        """
        Update the strategy's attributes.

        Args:
            validator_node_list (list[ValidatorNode]): The list with (new) validator node information
        """
        print("Updating the strategy's network information")
        self.validator_node_list = validator_node_list
        self.node_amount = len(validator_node_list)

        self.network_partitions = [[node.peer.port for node in validator_node_list]]
        self.port_dict = {
            port: index for index, port in enumerate(self.network_partitions[0])
        }
        self.communication_matrix = [
            [True for _ in range(self.node_amount)] for _ in range(self.node_amount)
        ]
        self.message_action_matrix = [
            [MessageAction() for _ in range(self.node_amount)]
            for _ in range(self.node_amount)
        ]

    def idx(self, port: int) -> int:
        """
        Transform a port to its corresponding index.

        Args:
            port: The port of which the index is needed.

        Returns:
            int: The corresponding index
        """
        return self.port_dict[port]

    @abstractmethod
    def handle_packet(self, packet: bytes) -> Tuple[bytes, int]:
        """
        This method is responsible for returning a possibly mutated packet and an action.

        Args:
            packet: the original packet.

        Returns:
            Tuple[bytes, int]: the new packet and the action.
        """
        pass
