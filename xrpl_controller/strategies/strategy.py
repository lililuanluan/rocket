"""This module is responsible for defining the Strategy interface."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Tuple

from loguru import logger

from protos import packet_pb2, ripple_pb2
from xrpl_controller.helper import (
    MAX_U32,
    format_datetime,
    yaml_to_dict,
)
from xrpl_controller.iteration_type import LedgerBasedIteration, TimeBasedIteration
from xrpl_controller.network_manager import NetworkManager
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
        iteration_type: TimeBasedIteration | None = None,
    ):
        """
        Initialize the Strategy interface with necessary fields.

        Args:
            network_config_path (str): The path of a network configuration file
            strategy_config_path (str): The path of the strategy configuration file
            auto_partition (bool, optional): Whether the strategy will auto-apply network partitions.
            auto_parse_identical (bool, optional): Whether the strategy will perform same actions on identical messages.
            auto_parse_subsets (bool, optional): Whether the strategy will perform same actions on defined subsets.
            keep_action_log (bool, optional): Whether the strategy will keep an action log. Defaults to True.
            iteration_type (IterationType, optional): Type of iteration logic to use.
        """
        self.network = NetworkManager(
            auto_parse_identical=auto_parse_identical,
            auto_parse_subsets=auto_parse_subsets,
        )
        self.auto_partition: bool = auto_partition
        self.auto_parse_identical = auto_parse_identical
        self.auto_parse_subsets = auto_parse_subsets
        self.keep_action_log = keep_action_log
        self.network.network_config, self.params = self.init_configs(
            network_config_path, strategy_config_path
        )

        self.start_datetime: datetime = datetime.now()
        self.iteration_type = (
            LedgerBasedIteration(10, 5, 45)
            if iteration_type is None
            else iteration_type
        )
        self.iteration_type.set_log_dir(format_datetime(self.start_datetime))

    @staticmethod
    def init_configs(
        network_config_path: str, strategy_config_path: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
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

    def update_network(self, validator_node_list: List[ValidatorNode]):
        """
        Update the strategy's attributes.

        Args:
            validator_node_list (list[ValidatorNode]): The list with (new) validator node information.
        """
        logger.info("Updating the strategy's network information")
        self.network.update_network(validator_node_list)
        self.iteration_type.set_validator_nodes(validator_node_list)
        self.setup()

    def update_status(self, packet: packet_pb2.Packet):
        """
        Update the iteration's state variables, when a new TMStatusChange is received.

        Args:
            packet: The packet to check for a possible status update.
        """
        try:
            message, _ = PacketEncoderDecoder.decode_packet(packet)
            if isinstance(message, ripple_pb2.TMStatusChange):
                self.iteration_type.on_status_change(message)
        except DecodingNotSupportedError:
            pass

    def process_packet(
        self,
        packet: packet_pb2.Packet,
    ) -> Tuple[bytes, int]:
        """
        Process an incoming packet, applies automatic processes if applicable.

        Args:
            packet: The packet to process.

        Returns:
            Tuple[bytes, int]: The processed packet as bytes and an action in a tuple.
        """
        peer_from_id = self.network.port_to_id(packet.from_port)
        peer_to_id = self.network.port_to_id(packet.to_port)

        # Check for identical previous messages or for identical messages within broadcasts.
        # This uses booleans to check whether the functionality has to be applied automatically.
        # First check whether we want to automatically parse re-sent messages,
        # then we check whether we want to perform identical actions for defined subsets of processes/peers.
        if (
            self.auto_parse_identical
            and (
                result := self.network.check_previous_message(
                    peer_from_id, peer_to_id, packet.data
                )
            )[0]
        ) or (
            self.auto_parse_subsets
            and (
                result := self.network.check_subsets(
                    peer_from_id, peer_to_id, packet.data
                )
            )[0]
        ):
            # If result[0] is True, then result[1] will contain usable data
            (final_data, action) = result[1]

        # Handle the packet regularly
        else:
            # If no communication is allowed by partitions, then we drop immediately
            if self.auto_partition and not self.network.check_communication(
                peer_from_id, peer_to_id
            ):
                (final_data, action) = (packet.data, MAX_U32)
            else:
                (final_data, action) = self.handle_packet(packet)

            # This is needed to keep track of previously sent messages
            if self.auto_parse_identical or self.auto_parse_subsets:
                self.network.set_message_action(
                    peer_from_id, peer_to_id, packet.data, final_data, action
                )

        self.update_status(packet)
        return final_data, action

    @abstractmethod
    def setup(self):  # pragma: no cover
        """
        Setup method to be implemented by implementations of Strategy, not required.

        This method gets called at the end of update_network to initialize starting values.
        """
        pass

    @abstractmethod
    def handle_packet(
        self, packet: packet_pb2.Packet
    ) -> Tuple[bytes, int]:  # pragma: no cover
        """
        This method is responsible for returning a possibly mutated packet and an action.

        Args:
            packet: The original packet.

        Returns:
            Tuple[bytes, int]: The new packet and the action.
        """
        pass
