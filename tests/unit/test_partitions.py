"""Tests for network partitions functionality."""

from tests.test_strategy import node_0, node_1, node_2
from xrpl_controller.strategies.random_fuzzer import RandomFuzzer

# Ports of the imported nodes are 10, 11, 12 respectively


def test_custom_connections():
    """Test whether Strategy attributes get updated correctly when connect_nodes is called."""
    strategy = RandomFuzzer()
    strategy.update_network([node_0, node_1, node_2])
    strategy.disconnect_nodes(10, 11)
    assert strategy.communication_matrix == [
        [False, False, True],
        [False, False, True],
        [True, True, False],
    ]

    assert not strategy.check_communication(10, 11)
    assert not strategy.check_communication(11, 10)

    strategy.connect_nodes(10, 11)
    assert strategy.communication_matrix == [
        [False, True, True],
        [True, False, True],
        [True, True, False],
    ]

    assert strategy.check_communication(10, 11)
    assert strategy.check_communication(11, 10)

    try:
        strategy.check_communication(10, 10)
        raise AssertionError()
    except ValueError:
        pass

    try:
        strategy.disconnect_nodes(10, 10)
        raise AssertionError()
    except ValueError:
        pass

    try:
        strategy.connect_nodes(11, 11)
        raise AssertionError()
    except ValueError:
        pass


def test_reset_communications():
    """Test whether Strategy attributes resets communication matrix correctly when reset_communications is called."""
    strategy = RandomFuzzer()
    strategy.update_network([node_0, node_1, node_2])
    strategy.partition_network([[10], [11, 12]])
    strategy.reset_communications()
    assert strategy.communication_matrix == [
        [False, True, True],
        [True, False, True],
        [True, True, False],
    ]


def test_partition_network_0():
    """Test whether Strategy attributes get updated correctly when partition_network is called. Formation 0."""
    strategy = RandomFuzzer()
    strategy.update_network([node_0, node_1, node_2])
    strategy.partition_network([[10], [11, 12]])
    assert strategy.communication_matrix == [
        [False, False, False],
        [False, False, True],
        [False, True, False],
    ]


def test_partition_network_1():
    """Test whether Strategy attributes get updated correctly when partition_network is called. Formation 1."""
    strategy = RandomFuzzer()
    strategy.update_network([node_0, node_1, node_2])
    strategy.partition_network([[10, 11, 12]])
    assert strategy.communication_matrix == [
        [False, True, True],
        [True, False, True],
        [True, True, False],
    ]


def test_partition_network_2():
    """Test whether Strategy attributes get updated correctly when partition_network is called."""
    strategy = RandomFuzzer()
    strategy.update_network([node_0, node_1, node_2])
    strategy.partition_network([[10], [11], [12]])
    assert strategy.communication_matrix == [
        [False, False, False],
        [False, False, False],
        [False, False, False],
    ]


def test_partition_network_invalid_partitions():
    """Test whether invalid partitions get rejected. Missing port."""
    strategy = RandomFuzzer()
    strategy.update_network([node_0, node_1, node_2])
    try:
        strategy.partition_network([[10], [12]])
        raise AssertionError()
    except ValueError:
        pass


def test_partition_network_invalid_amount():
    """Test whether invalid partitions get rejected. Duplicated port."""
    strategy = RandomFuzzer()
    strategy.update_network([node_0, node_1, node_2])
    try:
        strategy.partition_network([[10], [11, 11, 12]])
        raise AssertionError()
    except ValueError:
        pass


def test_apply_partition():
    """Test whether partitions get applied correctly."""
    strategy = RandomFuzzer()
    strategy.update_network([node_0, node_1, node_2])
    strategy.partition_network([[10, 11], [12]])
    assert strategy.check_communication(10, 11)
    assert strategy.check_communication(10, 11)
    assert not strategy.check_communication(10, 12)
    assert not strategy.check_communication(12, 10)
    assert not strategy.check_communication(11, 12)

    # Test whether exception gets raised when ports are equal
    try:
        assert not strategy.check_communication(12, 12)
        raise AssertionError()
    except ValueError:
        pass

    assert strategy.check_communication(11, 10)
