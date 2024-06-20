"""Class that holds information about a network of validator nodes."""

from typing import Any

import base58

from xrpl_controller.validator_node_info import ValidatorNode


class NetworkManager:
    """Class which holds and handles information related to a network of validator nodes."""

    def __init__(self):
        """Initialize fields for this object."""
        self.network_config: dict[str, Any] = {}
        self.validator_node_list: list[ValidatorNode] = []
        self.public_to_private_key_map: dict[str, str] = {}
        self.node_amount: int = 0
        self.port_to_id_dict: dict[int, int] = {}
        self.id_to_port_dict: dict[int, int] = {}

    def update_network(self, validator_node_list: list[ValidatorNode]):
        """Update the network with a list of validator nodes."""
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
