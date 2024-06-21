"""This module is responsible for defining the Strategy interface."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Dict, List, Tuple

import base58
from loguru import logger

from protos import packet_pb2, ripple_pb2
from xrpl_controller.core import (
    MAX_U32,
    flatten,
    format_datetime,
    parse_to_2d_list_of_ints,
    parse_to_list_of_ints,
    validate_ports_or_ids,
    yaml_to_dict,
)
from xrpl_controller.iteration_type import (
    IterationType,
    LedgerIteration,
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
        network_config_path: str = "./xrpl_controller/network_configs/default-network-config.yaml",
        strategy_config_path: str = "./xrpl_controller/strategies/configs/default-strategy-config.yaml",
        auto_partition: bool = True,
        auto_parse_identical: bool = True,
        auto_parse_subsets: bool = True,
        keep_action_log: bool = True,
        iteration_type: IterationType | None = None,
    ):
        """
        Initialize the Strategy interface with needed fields.

        Args:
            network_config_path (str): The path of a network configuration file
            strategy_config_path (str): The path of the strategy configuration file
            auto_partition (bool, optional): Whether the strategy will auto-apply network partitions.
            auto_parse_identical (bool, optional): Whether the strategy will perform same actions on identical messages.
            auto_parse_subsets (bool, optional): Whether the strategy will perform same actions on defined subsets.
            keep_action_log (bool, optional): Whether the strategy will keep an action log. Defaults to True.
            iteration_type (IterationType, optional): Type of iteration logic to use.
        """
        self.validator_node_list: List[ValidatorNode] = []
        self.public_to_private_key_map: Dict[str, str] = {}
        self.node_amount: int = 0
        self.port_to_id_dict: dict[int, int] = {}
        self.id_to_port_dict: dict[int, int] = {}
        self.auto_partition: bool = auto_partition
        self.communication_matrix: list[list[bool]] = []
        self.auto_parse_identical = auto_parse_identical
        self.auto_parse_subsets = auto_parse_subsets
        self.prev_message_action_matrix: list[list[MessageAction]] = []
        self.subsets_dict: dict[int, list[list[int]] | list[int]] = {}
        self.keep_action_log = keep_action_log
        self.network_config, self.params = self.init_configs(
            network_config_path, strategy_config_path
        )

        self.start_datetime: datetime = datetime.now()
        self.iteration_type = (
            LedgerIteration(10, 5) if iteration_type is None else iteration_type
        )
        self.iteration_type.set_log_dir(format_datetime(self.start_datetime))

    @staticmethod
    def init_configs(network_config_path: str, strategy_config_path: str):
        """Initialize the strategy and network configuration from the given paths."""
        params = yaml_to_dict(strategy_config_path)
        logger.debug(
            f"Initialized strategy parameters from configuration file:\n\t{params}"
        )

        network_config = yaml_to_dict(network_config_path)
        logger.debug(
            f"Initialized strategy network configuration from configuration file:\n\t{network_config}"
        )
        return network_config, params

    def partition_network(self, partitions: list[list[int]]):
        """
        Set the network partition and update the communication matrix. This overrides any preceding communications.

        Args:
            partitions (list[list[int]]): List containing the network partitions (as lists of peer ID's).

        Raises:
            ValueError: if given partitions are invalid.
        """
        flattened_partitions = flatten(partitions)
        if (
            set(flattened_partitions)
            != set([peer_id for peer_id in range(len(self.validator_node_list))])
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
                    peer_id_1 = partition[i]
                    peer_id_2 = partition[j]

                    self.communication_matrix[peer_id_1][peer_id_2] = True
                    self.communication_matrix[peer_id_2][peer_id_1] = True

    def connect_nodes(self, peer_id_1: int, peer_id_2: int):
        """
        Connect 2 nodes using their ID's, which allows communication between them.

        Args:
            peer_id_1 (int): Peer ID 1.
            peer_id_2 (int): Peer ID 2.

        Raises:
            ValueError: if peer_id_1 is equal to peer_id_2 or if any is negative.
        """
        validate_ports_or_ids(peer_id_1, peer_id_2)
        self.communication_matrix[peer_id_1][peer_id_2] = True
        self.communication_matrix[peer_id_2][peer_id_1] = True

    def disconnect_nodes(self, peer_id_1: int, peer_id_2: int):
        """
        Disconnect 2 nodes using their ID's, which disallows communication between them.

        Args:
            peer_id_1 (int): Peer ID 1.
            peer_id_2 (int): Peer ID 2.

        Raises:
            ValueError: if peer_id_1 is equal to peer_id_2 or if any is negative.
        """
        validate_ports_or_ids(peer_id_1, peer_id_2)
        self.communication_matrix[peer_id_1][peer_id_2] = False
        self.communication_matrix[peer_id_2][peer_id_1] = False

    def check_communication(self, peer_from_id: int, peer_to_id: int) -> bool:
        """
        Check whether 2 peers can communicate with each other using their ID's.

        Args:
            peer_from_id (int): The peer ID from where the message was sent.
            peer_to_id (int): The peer ID to where the message was sent.

        Returns:
            bool: A boolean indicating whether communication is permitted between the 2 given ID's.

        Raises:
            ValueError: if peer_from_id is equal to peer_to_id or if any is negative.
        """
        validate_ports_or_ids(peer_from_id, peer_to_id)
        return self.communication_matrix[peer_from_id][peer_to_id]

    def reset_communications(self):
        """
        Reset all communications, falling back to the network configuration.

        This method uses partition_network to rebuild the communication matrix in a correct way.
        """
        self.partition_network(
            [[peer_id for peer_id in range(len(self.validator_node_list))]]
        )

    def set_subsets_dict_entry(
        self, peer_id: int, subsets: list[list[int]] | list[int]
    ):
        """
        Set individual entries in the subsets_dict field.

        Args:
            peer_id (int): The peer ID.
            subsets (list[list[int]]): The list of subsets.

        Raises:
            ValueError: If auto_parse_subsets is False.
        """
        if not self.auto_parse_subsets:
            raise ValueError(
                "auto_parse_subsets must be set to True when calling set_subsets_dict_entry."
            )
        self.subsets_dict[peer_id] = subsets

    def set_subsets_dict(self, subsets_dict: dict[int, list[list[int]] | list[int]]):
        """
        Set the subsets_dict field, this will overwrite any previous modifications.

        Args:
            subsets_dict: The new dictionaries, a 'map' of ID's to subsets of ID's, to be used.

        Raise:
            ValueError: if auto_parse_subsets is False.
        """
        if not self.auto_parse_subsets:
            raise ValueError(
                "auto_parse_subsets must be set to True when calling set_subsets_dict."
            )

        self.subsets_dict = {peer_id: [] for peer_id in range(self.node_amount)}

        for peer_id, subsets in subsets_dict.items():
            self.set_subsets_dict_entry(peer_id, subsets)

    def set_message_action(
        self,
        peer_from_id: int,
        peer_to_id: int,
        initial_message: bytes,
        final_message: bytes,
        action: int,
    ):
        """
        Set an entry in the message_action_matrix.

        Args:
            peer_from_id: Sender peer ID.
            peer_to_id: Receiving peer ID.
            initial_message: The pre-processed message.
            final_message: The (possibly mutated) processed message
            action: The taken action

        Raises:
            ValueError: if auto_parse_identical and auto_parse_subsets are False, and if peer_from_id is equal to peer_to_id or if any is negative
        """
        if not (self.auto_parse_identical or self.auto_parse_subsets):
            raise ValueError(
                "auto_parse_subsets must be set to True when calling set_message_action."
            )

        validate_ports_or_ids(peer_from_id, peer_to_id)
        self.prev_message_action_matrix[peer_from_id][peer_to_id].set_initial_message(
            initial_message
        ).set_final_message(final_message).set_action(action)

    def check_previous_message(
        self, peer_from_id: int, peer_to_id: int, message: bytes
    ) -> tuple[bool, tuple[bytes, int]]:
        """
        Parse a message automatically to a final state with an action if it was matching to the previous message.

        Example Usage (Pseudocode):
            res: (bool, (bytes, int)) = check_previous_message(id_1, id_2, message)
            if res[0] then (message, action) = res[1]
            else: ...

        Args:
            peer_from_id: Sender peer ID.
            peer_to_id: Receiving peer ID.
            message: The message to be checked for parsing

        Returns:
            Tuple(bool, Tuple(bytes, int)): Boolean indicating success along with final message and action.

        Raises:
            ValueError: if auto_parse_identical and auto_parse_subsets are False.
        """
        if not (self.auto_parse_identical or self.auto_parse_subsets):
            raise ValueError(
                "auto_parse_subsets or auto_parse_identical must be set to True when calling check_previous_message."
            )

        message_action = self.prev_message_action_matrix[peer_from_id][peer_to_id]
        return message == message_action.initial_message, (
            message_action.final_message,
            message_action.action,
        )

    def check_subset_entry(
        self, peer_from_id: int, peer_to_id: int, message: bytes, subset: list[int]
    ) -> tuple[bool, tuple[bytes, int]]:
        """
        Check a subset for identical messages.

        Args:
            peer_from_id: Sender peer ID.
            peer_to_id: Receiving peer ID.
            message: The message to be checked for parsing
            subset: The subset of ID's to check

        Returns:
            A tuple indicating success along with final message and action.
        """
        # For the subset which peer_to_id is in, check whether an identical message can be found.
        # If one is found, we automatically parse it to the processed version with its action.
        if peer_to_id in subset:
            for peer_id in subset:
                if (
                    result := self.check_previous_message(
                        peer_from_id, peer_id, message
                    )
                )[0]:
                    # result is a tuple[bool, tuple[bytes, int]]
                    # The second tuple contains the processed message and an action
                    self.set_message_action(
                        peer_from_id, peer_to_id, message, result[1][0], result[1][1]
                    )
                    return result

        return False, self.check_previous_message(peer_from_id, peer_to_id, message)[1]

    def check_subsets(
        self, peer_from_id: int, peer_to_id: int, message: bytes
    ) -> tuple[bool, tuple[bytes, int]]:
        """
        Check multiple subsets for identical messages.

        Args:
            peer_from_id: Sender peer ID.
            peer_to_id: Receiving peer ID.
            message: The message to be checked for parsing

        Returns:
            A tuple indicating success along with final message and action.

        Raises:
            ValueError: if auto_parse_identical is False.
        """
        if not self.auto_parse_subsets:
            raise ValueError(
                "auto_parse_subsets must be set to True when calling check_subsets."
            )

        # self.subsets_dict[peer_from_id] can contain a 1- or 2-dimensional integer list
        # We first check whether the list is 2-dimensional, if so, we handle the entry accordingly
        if len(self.subsets_dict[peer_from_id]) > 0 and isinstance(
            self.subsets_dict[peer_from_id][0], list
        ):
            # We have to parse the list to a list[list[int]] type to suppress tox
            for subset in parse_to_2d_list_of_ints(self.subsets_dict[peer_from_id]):
                if (
                    result := self.check_subset_entry(
                        peer_from_id, peer_to_id, message, subset
                    )
                )[0]:
                    return result
            return False, self.check_previous_message(
                peer_from_id, peer_to_id, message
            )[1]
        else:
            # In this branch, we know for certain that self.subsets_dict[peer_from_id] is 1-dimensional
            # We have to parse the list to a list[int] type to suppress tox
            return self.check_subset_entry(
                peer_from_id,
                peer_to_id,
                message,
                parse_to_list_of_ints(self.subsets_dict[peer_from_id]),
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
        self.port_to_id_dict = {
            port: index
            for index, port in enumerate(
                [node.peer.port for node in validator_node_list]
            )
        }
        self.id_to_port_dict = {
            index: port
            for index, port in enumerate(
                [node.peer.port for node in validator_node_list]
            )
        }

        self.partition_network(
            [[peer_id for peer_id in range(len(validator_node_list))]]
        )

        if self.auto_parse_identical:
            self.prev_message_action_matrix = [
                [MessageAction() for _ in range(self.node_amount)]
                for _ in range(self.node_amount)
            ]

        if self.auto_parse_subsets:
            self.subsets_dict = {peer_id: [] for peer_id in range(self.node_amount)}

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
        self.iteration_type.set_validator_nodes(validator_node_list)

    def update_status(self, packet: packet_pb2.Packet):
        """Update the iteration's state variables, when a new TMStatusChange is received."""
        try:
            message, _ = PacketEncoderDecoder.decode_packet(packet)
            if isinstance(message, ripple_pb2.TMStatusChange):
                self.iteration_type.on_status_change(message)
        except DecodingNotSupportedError:
            pass

    def port_to_id(self, port: int) -> int:
        """
        Transform a port to its corresponding index.

        Args:
            port: The port of which the corresponding peer ID is needed.

        Returns:
            int: The corresponding peer ID

        Raises:
            ValueError: if port is not found in port_dict
        """
        try:
            return self.port_to_id_dict[port]
        except KeyError as err:
            raise ValueError(f"Port {port} not found in port_dict") from err

    def id_to_port(self, peer_id: int) -> int:
        """
        Transform a peer ID to its corresponding port.

        Args:
            peer_id: the peer ID of which the port is needed

        Returns:
            The corresponding port

        Raises:
            ValueError: if peer_id is not found in port_dict
        """
        try:
            return self.id_to_port_dict[peer_id]
        except KeyError as err:
            raise ValueError(f"pper ID {peer_id} not found in port_dict") from err

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
        peer_from_id = self.port_to_id(packet.from_port)
        peer_to_id = self.port_to_id(packet.to_port)

        # Check for identical previous messages or for identical messages within broadcasts.
        # This uses booleans to check whether the functionality has to be applied automatically.
        # First check whether we want to automatically parse resent messages,
        # then we check whether we want to perform identical actions for defined subsets of processes
        if (
            self.auto_parse_identical
            and (
                result := self.check_previous_message(
                    peer_from_id, peer_to_id, packet.data
                )
            )[0]
        ) or (
            self.auto_parse_subsets
            and (result := self.check_subsets(peer_from_id, peer_to_id, packet.data))[0]
        ):
            # If result[0] is True, then result[1] will contain usable data
            (final_data, action) = result[1]

        # Handle the packet regularly
        else:
            # If no communication is allowed by partitions, then we drop immediately
            if self.auto_partition and not self.check_communication(
                peer_from_id, peer_to_id
            ):
                (final_data, action) = (packet.data, MAX_U32)
            else:
                (final_data, action) = self.handle_packet(packet)

            # This is needed to keep track of previously sent messages
            if self.auto_parse_identical or self.auto_parse_subsets:
                self.set_message_action(
                    peer_from_id, peer_to_id, packet.data, final_data, action
                )

        self.update_status(packet)

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
