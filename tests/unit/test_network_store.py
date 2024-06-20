"""Tests for NetworkStore class."""

from tests.variable_store import node_0, node_1
from xrpl_controller.network_store import NetworkStore


def test_init():
    """Test the __init__ method."""
    store = NetworkStore()
    assert store.network_config == {}
    assert store.validator_node_list == []
    assert store.node_amount == 0
    assert store.port_to_id_dict == {}
    assert store.id_to_port_dict == {}
    assert store.public_to_private_key_map == {}


def test_update_network():
    """Test the update_network method."""
    store = NetworkStore()
    store.update_network([node_0, node_1])
    assert store.network_config == {}
    assert store.validator_node_list == [node_0, node_1]
    assert store.node_amount == 2
    assert store.port_to_id_dict == {10: 0, 11: 1}
    assert store.id_to_port_dict == {0: 10, 1: 11}
    assert store.public_to_private_key_map == {
        "643978c4": "c548734c",
        "f82580": "3a9c94",
    }
