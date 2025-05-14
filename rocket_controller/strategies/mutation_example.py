"""This module contains the class that implements an example Strategy using simple mutation."""

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

class MutationExample(Strategy):
    """Class that Mutates all TMProposeSet messages."""

    def __init__(
        self,
        network_config_path: str = "./config/network/default_network.yaml",
        strategy_config_path: str | None = None,
        iteration_type = LedgerBasedIteration(10, 10, 80),
        network_overrides: Dict[str, Any] | None = None,
        strategy_overrides: Dict[str, Any] | None = None,
    ):
        """Initialize the MutationExample class.

        Args:
            network_config_path: The path to a network config file to be used.
            strategy_config_path: The path to a strategy config file to be used.
            iteration_type: The type of iteration to keep track of.
            network_overrides: A dictionary containing parameter names and values which override the network config.
            strategy_overrides: A dictionary containing parameter names and values which override the strategy config.
        """
        super().__init__(
            network_config_path=network_config_path,
            strategy_config_path=strategy_config_path,
            iteration_type=iteration_type,
            network_overrides=network_overrides,
            strategy_overrides=strategy_overrides,
        )

        if self.params["seed"] is not None:
            random.seed(self.params["seed"])

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
        """Setup method for MutationExample."""

    def handle_packet(self, packet: packet_pb2.Packet) -> Tuple[bytes, int, int]:
        """
        Handler method for receiving a packet.

        Args:
            packet: Packet to handle.

        Returns:
            Tuple[bytes, int, int]: A tuple of the possible mutated message as bytes, an action as int and the send amount.
        """
        # drop message
        choice: float = random.random()
        if choice < self.params["drop_probability"]:
            return packet.data, MAX_U32, 1
        # corrupt message
        elif choice < self.params["drop_probability"] + self.params["corrupt_probability"]:
            # additional checks: event.from == 3 && self.current_round > 1 ?
            # if self.current_round > 1 how do i know the current round? from TMstatusChange messages?
            # but what if there is an integrity violation? then that data could be inaccurate
            # from websockets?
            peer_from_id = self.network.port_to_id(packet.from_port)
            peer_to_id = self.network.port_to_id(packet.to_port)
            if peer_from_id == 3: # byzantine node
                corrupted_message = self.corrupt_message(packet.data)
                try:
                    PacketEncoderDecoder.decode_packet_data(corrupted_message) # use this just to check if the message is valid
                except DecodingNotSupportedError as e:
                    # Log the decoding error and return the original message
                    logger.info("Message mutation resulted in a syntactically incorrect message. Returning original.")
                    return packet.data, 0, 1
                except Exception as e:
                    # Log the decoding error and return the original message
                    logger.info(f"Message mutation resulted in an unexpected error: {e}. Returning original.")
                    return packet.data, 0, 1
                logger.info(f"Message was successfully mutated: {peer_from_id} -> {peer_to_id}")
                return (
                    corrupted_message,
                    0,
                    1,
                )
        # do nothing
        return packet.data, 0, 1
    
    def corrupt_message(self, message: bytes) -> bytes:
        # flip a random bit in a random byte of the message
        #message_bytes = bytearray(message)
        #index = random.randint(0, len(message_bytes) - 1)
        #bit_to_flip = 1 << random.randint(0, 7)
        #message_bytes[index] ^= bit_to_flip
        #return bytes(message_bytes)
    
        if len(message) <= 6:  # Ensure the message has enough bytes to mutate
            logger.error("Message is too short to corrupt beyond the 6th byte.")
            return message

        message_bytes = bytearray(message)
        # Select a random index starting from the 6th byte
        index = random.randint(6, len(message_bytes) - 1)
        bit_to_flip = 1 << random.randint(0, 7)
        message_bytes[index] ^= bit_to_flip
        return bytes(message_bytes)
