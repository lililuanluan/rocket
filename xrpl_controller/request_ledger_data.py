"""This module is responsible for requesting ledger data from the validator nodes."""

from typing import List

from xrpl_controller.validator_node_info import ValidatorNode
import xrpl_controller.strategies.strategy

validator_node_list_store: List[ValidatorNode] = []


def store_validator_node_info(validator_node_list: List[ValidatorNode]):
    """This function stores the validator node info."""
    global validator_node_list_store
    validator_node_list_store = validator_node_list
    xrpl_controller.strategies.strategy.validator_node_list_store = (
        validator_node_list_store
    )

    print(f"Stored validator node info: {validator_node_list_store}")
    return
