"""This module is responsible for defining the Strategy interface."""

import json
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple

import base58
import tomllib

from protos import packet_pb2
from xrpl_controller.core import MAX_U32, flatten
from xrpl_controller.validator_node_info import ValidatorNode


class Strategy(ABC):
    """Class that defines the Strategy interface."""

    def __init__(
        self,
        network_config_file: str | None = None,
        strategy_config_file: str | None = None,
        auto_partition: bool = True,
        keep_action_log: bool = True,
    ):
        """
        Initialize the Strategy interface with needed attributes.

        Args:
            network_config_file (str): The filename of a network configuration file
            strategy_config_file (str): The filename of a strategy configuration file.
            auto_partition (bool, optional): Whether the strategy will auto-apply network partitions. Defaults to True.
            keep_action_log (bool, optional): Whether the strategy will keep an action log. Defaults to True.
        """
        self.validator_node_list: List[ValidatorNode] = []
        self.public_to_private_key_map: Dict[str, str] = {}
        self.node_amount: int = 0
        self.network_partitions: list[list[int]] = []
        self.port_dict: Dict[int, int] = {}
        self.communication_matrix: list[list[bool]] = []
        self.auto_partition = auto_partition
        self.keep_action_log = keep_action_log
        self.params = {}

        str_config_file = (
            strategy_config_file + ".json"
            if strategy_config_file is not None
            and not strategy_config_file.endswith(".json")
            else strategy_config_file
        )
        config_path = "./xrpl_controller/strategies/configs/" + (
            self.__class__.__name__ + ".json"
            if str_config_file is None
            else str_config_file
        )

        with open(config_path, "rb") as f:
            self.params = json.load(f)
            print(
                "Initialized strategy parameters from configuration file:\n\t",
                self.params,
            )

        ntw_config_file = (
            network_config_file + ".toml"
            if network_config_file is not None and network_config_file.endswith(".toml")
            else network_config_file
        )
        network_config_path = "./xrpl_controller/network_configs/" + (
            "default-network-config.toml"
            if ntw_config_file is None
            else ntw_config_file
        )
        with open(network_config_path, "rb") as f:
            self.network_config = tomllib.load(f)
            print(
                "Initialized strategy network configuration from configuration file:\n\t",
                self.network_config,
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
        print("Updating the strategy's network information")
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

    @abstractmethod
    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int]:
        """
        This method is responsible for returning a possibly mutated packet and an action.

        Args:
            packet: the original packet.

        Returns:
            Tuple[bytes, int]: the new packet and the action.
        """
        pass
