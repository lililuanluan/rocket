"""This module contains the class that implements an ByzzFuzz Baseline Strategy."""

from datetime import datetime
from typing import Any, Dict, Tuple

from xrpl.utils import datetime_to_ripple_time

from protos import packet_pb2, ripple_pb2
from rocket_controller.encoder_decoder import (
    DecodingNotSupportedError,
    PacketEncoderDecoder,
)
from rocket_controller.iteration_type import TimeBasedIteration, LedgerBasedIteration
from rocket_controller.strategies.strategy import Strategy

from rocket_controller.helper import MAX_U32
import random

from loguru import logger

class ByzzFuzzBaseline(Strategy):
    """Class that Mutates all TMProposeSet messages (ByzzFuzz Baseline)."""
    def __init__(
        self,
        network_config_path: str | None = "./config/network/default_network.yaml",
        strategy_config_path: str | None = None,
        auto_partition: bool = True,
        auto_parse_identical: bool = True,
        auto_parse_subsets: bool = True,
        keep_action_log: bool = True,
        iteration_type = LedgerBasedIteration(100, 15, 130),
        log_dir: str | None = None,
        network_overrides: Dict[str, Any] | None = None,
        strategy_overrides: Dict[str, Any] | None = None,
    ):
        """Initialize the ByzzFuzzBaseline class.

        Args:
            network_config_path: The path to a network config file to be used.
            strategy_config_path: The path to a strategy config file to be used.
            iteration_type: The type of iteration to keep track of.
            network_overrides: A dictionary containing parameter names and values which override the network config.
            strategy_overrides: A dictionary containing parameter names and values which override the strategy config.
        """
        super().__init__(
            network_config_path,
            strategy_config_path,
            auto_partition,
            auto_parse_identical,
            auto_parse_subsets,
            keep_action_log,
            iteration_type,
            log_dir,
            network_overrides,
            strategy_overrides,
        )

        if self.params["drop_probability"] < 0 or self.params["corrupt_probability"] < 0:
            raise ValueError(
                f"drop and corrupt probabilities must be non-negative, drop_probability: {self.params['drop_probability']}, corrupt_probability: {self.params['corrupt_probability']}"
            )

        if (self.params["drop_probability"] + self.params["corrupt_probability"]) > 1.0:
            raise ValueError(
                f"drop and corrupt probabilities must sum to less than or equal to 1.0, but was \
                {self.params['drop_probability'] + self.params['corrupt_probability']}"
            )

    def setup(self):
        """Setup method for ByzzFuzzBaseline."""

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int, int]:
        """
        Handler method for receiving a packet.

        Args:
            packet: Packet to handle.

        Returns:
            Tuple[bytes, int, int]: A tuple of the possible mutated message as bytes, an action as int and the send amount.
        """
        #cur_ledger_infos = self.iteration_type.ledger_validation_map.values()
        #if cur_ledger_infos:
        #    logger.debug("Current ledger seq status: " + ", ".join(str(entry['seq']) for entry in cur_ledger_infos))

        # drop message
        peer_from_id = self.network.port_to_id(packet.from_port)
        peer_to_id = self.network.port_to_id(packet.to_port)

        if self.get_current_round_of_node(peer_from_id)>8:
            # do nothing, let network heal
            return packet.data, 0, 1
        choice: float = random.random()
        if choice < self.params["drop_probability"]:
            logger.debug(f"Dropping message from {peer_from_id} to {peer_to_id}, round: {self.get_current_round_of_node(peer_from_id)}...")
            return packet.data, MAX_U32, 1
        # corrupt message
        elif choice < self.params["drop_probability"] + self.params["corrupt_probability"]:
            if peer_from_id in self.iteration_type._byzantine_nodes and self.get_current_round_of_node(peer_from_id)>1: # byzantine node
                logger.debug(f"Mutating message from {peer_from_id} to {peer_to_id}, round: {self.get_current_round_of_node(peer_from_id)}...")
                corrupted_message, byte_flipped, bit_flipped = self.corrupt_message(packet.data)
                try:
                    message, message_type = PacketEncoderDecoder.decode_packet_data(corrupted_message) # use this just to check if the message is valid
                except DecodingNotSupportedError as e:
                    logger.info("Message mutation resulted in a syntactically incorrect message. Returning original.")
                    return packet.data, 0, 1
                except Exception as e:
                    logger.info(f"Message mutation resulted in an unexpected error: {e}. Returning original.")
                    return packet.data, 0, 1
                logger.debug(f"Corrupting message which was {message} and now is {corrupted_message}, byte flipped: {byte_flipped}, bit flipped: {bit_flipped}")
                return (
                    corrupted_message,
                    0,
                    1,
                )
        # do nothing
        return packet.data, 0, 1
    
    def corrupt_message(self, message: bytes) -> tuple[bytes, int, int]:
        # flip a random bit in a random byte of the message
    
        if len(message) <= 6:  # ensure the message has enough bytes to mutate
            logger.error("Message is too short to corrupt beyond the 6th byte.")
            return message, -1, -1

        message_bytes = bytearray(message)
        # mutate message payload
        index = random.randint(6, len(message_bytes) - 1)
        bit_to_flip = 1 << random.randint(0, 7)
        message_bytes[index] ^= bit_to_flip
        return bytes(message_bytes), index, bit_to_flip

    def check_current_round(self):
        """Check if the current round is greater than 1 and if so, return True."""
        cur_ledger_infos = self.iteration_type.ledger_validation_map.values()
        if cur_ledger_infos and all(entry["seq"] > 1 for entry in cur_ledger_infos):
            return True
        return False

    def get_current_round_of_node(self, node_id: int) -> int:
        """Check if the current round is greater than 1 and if so, return True."""
        for _node_id, entry in self.iteration_type.ledger_validation_map.items():
            if node_id == _node_id:
                return entry["seq"]
        return -1