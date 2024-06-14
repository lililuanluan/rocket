"""This module is responsible for defining the Strategy interface."""

import struct
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple

import base58
from loguru import logger

from protos import packet_pb2, ripple_pb2
from xrpl_controller.core import MAX_U32, flatten, validate_ports
from xrpl_controller.iteration_type import (
    IterationType,
    LedgerBasedIteration,
    TimeBasedIteration,
)
from xrpl_controller.message_action import MessageAction
from xrpl_controller.strategies.encoder_decoder import (
    DecodingNotSupportedError,
    PacketEncoderDecoder,
)
from xrpl_controller.validator_node_info import ValidatorNode


class Strategy(ABC):
    """Class that defines the Strategy interface."""

    def __init__(
        self,
        auto_partition: bool = True,
        auto_parse_identical: bool = True,
        keep_action_log: bool = True,
        iteration_type: IterationType | None = None,
    ):
        """
        Initialize the Strategy interface with needed fields.

        Args:
            auto_partition (bool, optional): Whether the strategy automatically applies network partitions.
            auto_parse_identical (bool, optional): Whether the strategy will perform same actions on identical messages.
            Defaults to True.
            keep_action_log (bool, optional): Whether the strategy will keep an action log. Defaults to True.
            iteration_type (IterationType, optional): Type of iteration logic to use.
        """
        self.validator_node_list: List[ValidatorNode] = []
        self.public_to_private_key_map: Dict[str, str] = {}
        self.node_amount: int = 0
        self.port_dict: Dict[int, int] = {}
        self.auto_partition: bool = auto_partition
        self.communication_matrix: list[list[bool]] = []
        self.auto_parse_identical = auto_parse_identical
        if auto_parse_identical:
            self.prev_message_action_matrix: list[list[MessageAction]] = []
        self.keep_action_log = keep_action_log
        self.iteration_type = (
            LedgerBasedIteration(10, 5) if iteration_type is None else iteration_type
        )

    def partition_network(self, partitions: list[list[int]]):
        """
        Set the network partition and update the communication matrix. This overrides any preceding communications.

        Args:
            partitions (list[list[int]]): List containing the network partitions (as lists of port numbers).

        Raises:
            ValueError: if given partitions are invalid
        """
        flattened_partitions = flatten(partitions)
        if (
            set(flattened_partitions)
            != set([node.peer.port for node in self.validator_node_list])
            or len(flattened_partitions) != self.node_amount
        ):
            raise ValueError(
                "The given network partition is not valid for the current network."
            )

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

    def connect_nodes(self, peer_port_1: int, peer_port_2: int):
        """
        Connect 2 nodes using their ports, which allows communication between them.

        Args:
            peer_port_1 (int): Peer port 1.
            peer_port_2 (int): Peer port 2.

        Raises:
            ValueError: If peer_port_1 is equal to peer_port_2 or if any is negative
        """
        validate_ports(peer_port_1, peer_port_2)
        self.communication_matrix[self.idx(peer_port_1)][self.idx(peer_port_2)] = True
        self.communication_matrix[self.idx(peer_port_2)][self.idx(peer_port_1)] = True

    def disconnect_nodes(self, peer_port_1: int, peer_port_2: int):
        """
        Disconnect 2 nodes using their ports, which disallows communication between them.

        Args:
            peer_port_1 (int): Peer port 1.
            peer_port_2 (int): Peer port 2.

        Raises:
            ValueError: If peer_port_1 is equal to peer_port_2 or if any is negative
        """
        validate_ports(peer_port_1, peer_port_2)
        self.communication_matrix[self.idx(peer_port_1)][self.idx(peer_port_2)] = False
        self.communication_matrix[self.idx(peer_port_2)][self.idx(peer_port_1)] = False

    def check_communication(self, peer_from_port: int, peer_to_port: int) -> bool:
        """
        Check whether 2 ports can communicate with each other.

        Args:
            peer_from_port (int): The peer port from where the message was sent.
            peer_to_port (int): The peer port to where the message was sent.

        Returns:
            bool: A boolean indicating whether communication is permitted between the 2 given ports.

        Raises:
            ValueError: If peer_from_port is equal to peer_to_port or if any is negative
        """
        validate_ports(peer_from_port, peer_to_port)
        return self.communication_matrix[self.idx(peer_from_port)][
            self.idx(peer_to_port)
        ]

    def reset_communications(self):
        """
        Reset all communications, falling back to the network configuration.

        This method uses partition_network to rebuild the communication matrix in a correct way.
        """
        self.partition_network([[node.peer.port for node in self.validator_node_list]])

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

        Raises:
            ValueError: if peer_from_port is equal to peer_to_port or if any is negative
        """
        assert self.auto_parse_identical
        validate_ports(peer_from_port, peer_to_port)
        self.prev_message_action_matrix[self.idx(peer_from_port)][
            self.idx(peer_to_port)
        ].set_initial_message(initial_message).set_final_message(
            final_message
        ).set_action(action)

    def check_previous_message(
        self, peer_from_port: int, peer_to_port: int, message: bytes
    ) -> tuple[bool, tuple[bytes, int]]:
        """
        Parse a message automatically to a final state with an action if it was matching to the previous message.

        Example Usage (Pseudocode):
            res: (bool, (bytes, int)) = check_previous_message(port_1, port_2, message)
            if res[0] then (message, action) = res[1]
            else: ...

        Args:
            peer_from_port: Sender peer port.
            peer_to_port: Receiving peer port.
            message: The message to be checked for parsing

        Returns:
            Tuple(bool, Tuple(bytes, int)): Boolean indicating success along with final message and action.
        """
        assert self.auto_parse_identical
        message_action = self.prev_message_action_matrix[self.idx(peer_from_port)][
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
        logger.info("Updating the strategy's network information")
        self.validator_node_list = validator_node_list
        self.public_to_private_key_map.clear()
        self.node_amount = len(validator_node_list)
        self.port_dict = {
            port: index
            for index, port in enumerate(
                [node.peer.port for node in validator_node_list]
            )
        }

        self.partition_network([[node.peer.port for node in validator_node_list]])

        if self.auto_parse_identical:
            self.prev_message_action_matrix = [
                [MessageAction() for _ in range(self.node_amount)]
                for _ in range(self.node_amount)
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

    def idx(self, port: int) -> int:
        """
        Transform a port to its corresponding index.

        Args:
            port: The port of which the index is needed.

        Returns:
            int: The corresponding index
        """
        return self.port_dict[port]

    def process_packet(
        self,
        packet: packet_pb2.Packet,
    ) -> Tuple[bytes, int]:
        """
        Process an incoming packet, applies automatic processes if applicable.

        Args:
            packet: Packet object

        Returns:
            Tuple[bytes, int]: The processed packet as bytes and an action in a tuple.
        """
        if (
            self.auto_parse_identical
            and self.check_previous_message(
                packet.from_port, packet.to_port, packet.data
            )[0]
        ):
            (final_data, action) = self.check_previous_message(
                packet.from_port, packet.to_port, packet.data
            )[1]

        else:
            if self.auto_partition and not self.check_communication(
                packet.from_port, packet.to_port
            ):
                (final_data, action) = (packet.data, MAX_U32)
            else:
                (final_data, action) = self.handle_packet(packet)

            if self.auto_parse_identical:
                self.set_message_action(
                    packet.from_port, packet.to_port, packet.data, final_data, action
                )

        message_type = struct.unpack("!H", packet.data[4:6])[0]
        if message_type == 34:
            try:
                message, _ = PacketEncoderDecoder.decode_packet(packet)
                if isinstance(message, ripple_pb2.TMStatusChange):
                    self.update_status(message)
            except DecodingNotSupportedError:
                pass

        return final_data, action

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
