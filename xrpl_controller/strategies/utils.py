
from typing import List
from xrpl_controller.validator_node_info import ValidatorNode
from xrpl_controller.strategies.handling import validator_node_list_store


def getKeys(validator_node_list: List[ValidatorNode]):
    global validator_node_list_store
    validator_node_list_store = validator_node_list