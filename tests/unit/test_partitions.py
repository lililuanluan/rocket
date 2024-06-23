"""Tests for network partitions functionality."""

import pytest

from tests.default_test_variables import node_0, node_1, node_2
from xrpl_controller.network_manager import NetworkManager


def test_custom_connections():
    """Test whether Strategy attributes get updated correctly when connect_nodes is called."""
    network = NetworkManager()

    network.update_network([node_0, node_1, node_2])
    network.disconnect_nodes(0, 1)
    assert network.communication_matrix == [
        [False, False, True],
        [False, False, True],
        [True, True, False],
    ]

    assert not network.check_communication(0, 1)
    assert not network.check_communication(1, 0)

    network.connect_nodes(0, 1)
    assert network.communication_matrix == [
        [False, True, True],
        [True, False, True],
        [True, True, False],
    ]

    assert network.check_communication(0, 1)
    assert network.check_communication(1, 0)

    with pytest.raises(ValueError):
        network.check_communication(0, 0)

    with pytest.raises(ValueError):
        network.disconnect_nodes(0, 0)

    with pytest.raises(ValueError):
        network.connect_nodes(1, 1)


def test_reset_communications():
    """Test whether Strategy attributes resets communication matrix correctly when reset_communications is called."""
    network = NetworkManager()
    network.update_network([node_0, node_1, node_2])
    network.partition_network([[0], [1, 2]])
    network.reset_communications()
    assert network.communication_matrix == [
        [False, True, True],
        [True, False, True],
        [True, True, False],
    ]


def test_partition_network_0():
    """Test whether Strategy attributes get updated correctly when partition_network is called. Formation 0."""
    network = NetworkManager()
    network.update_network([node_0, node_1, node_2])
    network.partition_network([[0], [1, 2]])
    assert network.communication_matrix == [
        [False, False, False],
        [False, False, True],
        [False, True, False],
    ]


def test_partition_network_1():
    """Test whether Strategy attributes get updated correctly when partition_network is called. Formation 1."""
    network = NetworkManager()

    network.update_network([node_0, node_1, node_2])
    network.partition_network([[0, 1, 2]])
    assert network.communication_matrix == [
        [False, True, True],
        [True, False, True],
        [True, True, False],
    ]


def test_partition_network_2():
    """Test whether Strategy attributes get updated correctly when partition_network is called."""
    network = NetworkManager()

    network.update_network([node_0, node_1, node_2])
    network.partition_network([[0], [1], [2]])
    assert network.communication_matrix == [
        [False, False, False],
        [False, False, False],
        [False, False, False],
    ]


def test_partition_network_invalid_partitions():
    """Test whether invalid partitions get rejected. Missing port."""
    network = NetworkManager()
    network.update_network([node_0, node_1, node_2])
    with pytest.raises(ValueError):
        network.partition_network([[0], [2]])


def test_partition_network_invalid_amount():
    """Test whether invalid partitions get rejected. Duplicated port."""
    network = NetworkManager()
    network.update_network([node_0, node_1, node_2])
    with pytest.raises(ValueError):
        network.partition_network([[0], [1, 1, 2]])


def test_apply_partition():
    """Test whether partitions get applied correctly."""
    network = NetworkManager()
    network.update_network([node_0, node_1, node_2])
    network.partition_network([[0, 1], [2]])
    assert network.check_communication(0, 1)
    assert network.check_communication(0, 1)
    assert not network.check_communication(0, 2)
    assert not network.check_communication(2, 0)
    assert not network.check_communication(1, 2)

    # Test whether exception gets raised when ports are equal
    with pytest.raises(ValueError):
        network.check_communication(2, 2)

    assert network.check_communication(1, 0)
