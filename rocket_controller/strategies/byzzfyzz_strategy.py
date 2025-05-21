"""This module contains the class that implements an ByzzFuzz Strategy."""

from datetime import datetime
from typing import Any, Dict, Tuple
from itertools import chain, combinations

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

class ByzzFuzzStrategy(Strategy):
    def __init__(
        self,
        network_config_path: str = "./config/network/default_network.yaml",
        strategy_config_path: str | None = None,
        iteration_type = LedgerBasedIteration(10, 7, 300),
        network_overrides: Dict[str, Any] | None = None,
        strategy_overrides: Dict[str, Any] | None = None,
    ):
        """Initialize the ByzzFuzzStrategy class.

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

        logger.debug(f"{self.network.network_config["number_of_nodes"]} nodes in the network.") # 0 nodes, take it from iteration type

        self.rounds = self.params["rounds"]
        self.network_faults = self.params["network_faults"]
        self.process_faults = self.params["process_faults"]
        self.node_amount = self.network.network_config["number_of_nodes"]
        self.small_scope = self.params["small_scope"]

        self.iteration_type.register_callback(self.init_faults)
    
    def init_faults(self) -> None:
        self.network_faults_list = []
        self.process_faults_list = []

        for _ in range(self.network_faults):
            random_round = random.randint(1, self.rounds)
            # choose a random partition of the network
            random_partition = generate_random_partition(self.node_amount)
            self.network_faults_list.append((random_round, random_partition))

        for _ in range(self.process_faults):
            random_round = random.randint(1, self.rounds)
            # choose a random subset of receivers uniformly from all possible subsets
            random_receiver_nodes = generate_random_subset(self.node_amount)
            self.process_faults_list.append((random_round, random_receiver_nodes))

        logger.debug("Network faults (rounds and partitions):")
        for round_num, partition in self.network_faults_list:
            logger.debug(f"Round {round_num}: {partition}")

        logger.debug("Process faults (rounds and subsets):")
        for round_num, subset in self.process_faults_list:
            logger.debug(f"Round {round_num}: {subset}")

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
        peer_from_id = self.network.port_to_id(packet.from_port)
        peer_to_id = self.network.port_to_id(packet.to_port)

        """  
        if any(round_num == self.check_current_round() and 
               any(peer_from_id in subset1 and peer_to_id in subset2 for subset1 in partition for subset2 in partition if subset1 != subset2)
               for round_num, partition in self.network_faults_list):
            # drop message
            logger.debug(f"Dropping message from {peer_from_id} to {peer_to_id}")
            return packet.data, MAX_U32, 1
        """

        if peer_from_id in self.iteration_type._byzantine_nodes and any(round_num == self.check_current_round() and peer_to_id in receiver_nodes for round_num, receiver_nodes in self.process_faults_list):
            # mutation logic
            logger.debug(f"Mutating message from {peer_from_id} to {peer_to_id}, round: {self.check_current_round()}")
            try:
                message, message_type_no = PacketEncoderDecoder.decode_packet(packet)
            except DecodingNotSupportedError:
                logger.error(
                    f"Decoding of message type {message_type_no} not supported"	)
                return packet.data, 0, 1

            # Check whether message is of type TMProposeSet
            if isinstance(message, ripple_pb2.TMProposeSet):
                logger.debug(f"Mutating TMProposeSet message, round: {self.check_current_round()}")

        return packet.data, 0, 1
    
    def corrupt_message(self, packet: packet_pb2.Packet) -> tuple[bytes, int, int]:
        # do something to corrupt the message
        try:
            message, message_type_no = PacketEncoderDecoder.decode_packet(packet)
        except DecodingNotSupportedError:
            logger.error(
                f"Decoding of message type {message_type_no} not supported"	)
            return packet.data, 0, 1

        # Check whether message is of type TMProposeSet
        if isinstance(message, ripple_pb2.TMProposeSet):
            logger.debug(f"Corrupting TMProposeSet message, round: {self.check_current_round()}")
            return packet.data, 0, 1
            #return self.corrupt_TMProposeSet(message)
        elif isinstance(message, ripple_pb2.TMValidation):
            logger.debug(f"Corrupting TMValidation message, round: {self.check_current_round()}")
            return packet.data, 0, 1
        elif isinstance(message, ripple_pb2.TMTransaction):
            logger.debug(f"Corrupting TMTTransaction message, round: {self.check_current_round()}")
            return packet.data, 0, 1
        
        return packet.data, 0, 1


    
    def corrupt_TMProposeSet(self, message: bytes) -> tuple[bytes, int, int]:
        # Mutate the closeTime of each message
        message.closeTime = datetime_to_ripple_time(datetime.now())

        # message.proposeSeq
        # message.currentTxHash

        # Sign the message
        signed_message = PacketEncoderDecoder.sign_message(
            message,
            self.network.public_to_private_key_map[message.nodePubKey.hex()],
        )

        return (
            PacketEncoderDecoder.encode_message(signed_message, message_type_no),
            0,
            1,
        )


    def check_current_round(self):
        """Check if the current round is greater than 1 and if so, return True."""
        cur_ledger_infos = self.iteration_type.ledger_validation_map.values()
        if cur_ledger_infos and all(entry["seq"] > 1 for entry in cur_ledger_infos):
            return True
        return False

def generate_random_partition(node_count: int) -> list[set[int]]:
    nodes = list(range(node_count))
    partition = []
    while nodes:
        subset_size = random.randint(1, len(nodes))
        subset = set(random.sample(nodes, subset_size))
        partition.append(subset)
        nodes = [node for node in nodes if node not in subset]
    return partition
"""
Why It Is Not Uniform:

Subset Size Bias:
The subset_size is chosen randomly using random.randint(1, len(nodes)). This introduces a bias because subsets of certain sizes are more likely to be chosen than others.
For example, smaller subsets are less likely to be chosen compared to larger subsets when there are many nodes left.
Sequential Subset Selection:
The method selects subsets sequentially, which means the choice of one subset affects the remaining nodes and the subsequent subsets. This dependency introduces additional bias.

Should I generate all possible partitions and then randomly select one? This however impacts performance. Is there a smarter way like for generating random subsets?
"""

def generate_random_subset(node_count: int) -> set[int]:
    # uniformly choose a subset of nodes
    nodes = list(range(node_count))
    return set(node for node in nodes if random.choice([True, False]))