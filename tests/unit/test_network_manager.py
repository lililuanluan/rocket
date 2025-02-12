"""Tests for NetworkStore class."""

import sys
from io import StringIO
from unittest.mock import patch

import pytest
from xrpl.models import Response
from xrpl.models.response import ResponseStatus

from rocket_controller.network_manager import NetworkManager
from tests.default_test_variables import node_0, node_1


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
            assert len(item.messages) == 0


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


@patch("rocket_controller.network_manager.WebsocketClient")
@patch("rocket_controller.network_manager.autofill_and_sign", return_value=None)
@patch(
    "rocket_controller.network_manager.submit",
    return_value=Response(status=ResponseStatus.SUCCESS, result={}),
)
def test_submit_transaction(wsm, autofill_and_sign_mock, submit_mock):
    """Test whether method is creating transactions correctly and supposedly sending them to the correct address."""
    network = NetworkManager()
    captured_output = StringIO()
    sys.stdout = captured_output

    network.update_network([node_0, node_1])
    network.submit_transaction(1)

    sys.stdout = sys.__stdout__
    assert (
        "Sent a transaction submission to node 1, url: ws://test-ws-pub:21/"
        in captured_output.getvalue()
    )

    assert (
        autofill_and_sign_mock.call_args[0][0].blob()
        == "120000220000000061400000003B9ACA0073008114B5F762798A53D543A014CAF8B297CFF8F2F937E883145988EBB744055F4E8BDC7F67FD53EB9FCF961DC0"
    )
    assert network.tx_builder.transactions == [None]
    assert network.tx_builder.tx_amount == 1


def test_submit_transaction_exception():
    """Test whether a ValueError is raised when invalid ID is given."""
    network = NetworkManager()
    network.update_network([node_0, node_1])

    with pytest.raises(ValueError):
        network.submit_transaction(2)
