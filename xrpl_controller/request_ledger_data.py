"""This module is responsible for requesting ledger data from the validator nodes."""

from typing import List

from xrpl_controller.validator_node_info import ValidatorNode

validator_node_list_store: List[ValidatorNode] = []


def store_validator_node_info(validator_node_list: List[ValidatorNode]):
    """This function stores the validator node info."""
    global validator_node_list_store
    validator_node_list_store = validator_node_list
    print(f"Stored validator node info: {validator_node_list_store}")
    return
