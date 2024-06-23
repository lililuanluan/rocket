"""Tests for NetworkStore class."""
from unittest.mock import patch

import pytest

from tests.default_test_variables import node_0, node_1
from xrpl_controller.network_manager import NetworkManager


def test_init():
    """Test the __init__ method."""
    store = NetworkManager()
    assert store.network_config == {}
    assert store.validator_node_list == []
    assert store.node_amount == 0
    assert store.port_to_id_dict == {}
    assert store.id_to_port_dict == {}
    assert store.public_to_private_key_map == {}


def test_update_network():
    """Test the update_network method."""
    network = NetworkManager()
    network.update_network([node_0, node_1])
    assert network.network_config == {}
    assert network.validator_node_list == [node_0, node_1]
    assert network.node_amount == 2
    assert network.port_to_id_dict == {10: 0, 11: 1}
    assert network.id_to_port_dict == {0: 10, 1: 11}
    assert network.public_to_private_key_map == {
        "643978c4": "c548734c",
        "f82580": "3a9c94",
    }

    assert network.communication_matrix == [
        [False, True],
        [True, False],
    ]

    assert network.subsets_dict == {0: [], 1: []}

    assert len(network.prev_message_action_matrix) == 2
    for row in network.prev_message_action_matrix:
        assert len(row) == 2
        for item in row:
            assert item.initial_message == b""
            assert item.final_message == b""
            assert item.action == -1


def test_port_to_id_invalid():
    """Test whether port_to_id raises an error when an invalid port is given."""
    network = NetworkManager()
    network.port_to_id_dict = {10: 0, 11: 1, 12: 2}
    with pytest.raises(ValueError):
        network.port_to_id(0)


def test_id_to_port_invalid():
    """Test whether id_to_port raises an error when an invalid id is given."""
    network = NetworkManager()
    network.id_to_port_dict = {0: 10, 1: 11, 2: 12}
    with pytest.raises(ValueError):
        network.id_to_port(3)


@patch("xrpl_controller.network_manager.websocket.create_connection")
def test_submit_transaction(ws_client):
    network = NetworkManager()
    network.update_network([node_0, node_1])
    network.submit_transaction(0)

