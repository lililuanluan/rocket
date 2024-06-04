"""This module contains the class that implements a utility file."""

from typing import List

from xrpl_controller.validator_node_info import ValidatorNode


def getKeys(validator_node_list: List[ValidatorNode]):
    """
    returns the updated validator_node_list.

    Args:
       validator_node_list: List with all the validator nodes

    Returns: nothing

    """
    global validator_node_list_store
    validator_node_list_store = validator_node_list
