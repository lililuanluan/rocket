"""Tests for network partitions functionality."""

from unittest.mock import Mock, patch

from tests.unit.test_strategy import node_0, node_1, node_2
from xrpl_controller.strategies.random_fuzzer import RandomFuzzer

configs = (
    {
        "base_port_peer": 60000,
        "base_port_ws": 61000,
        "base_port_ws_admin": 62000,
        "base_port_rpc": 63000,
        "number_of_nodes": 3,
        "network_partition": [[0, 1, 2]],
    },
    {
        "delay_probability": 0.6,
        "drop_probability": 0,
        "min_delay_ms": 10,
        "max_delay_ms": 150,
        "seed": 10,
    },
)
# Ports of the imported nodes are 10, 11, 12 respectively


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_custom_connections(mock_init_configs):
    """Test whether Strategy attributes get updated correctly when connect_nodes is called."""
    strategy = RandomFuzzer(iteration_type=Mock())
    mock_init_configs.assert_called_once()

    strategy.update_network([node_0, node_1, node_2])
    strategy.disconnect_nodes(0, 1)
    assert strategy.communication_matrix == [
        [False, False, True],
        [False, False, True],
        [True, True, False],
    ]

    assert not strategy.check_communication(0, 1)
    assert not strategy.check_communication(1, 0)

    strategy.connect_nodes(0, 1)
    assert strategy.communication_matrix == [
        [False, True, True],
        [True, False, True],
        [True, True, False],
    ]

    assert strategy.check_communication(0, 1)
    assert strategy.check_communication(1, 0)

    try:
        strategy.check_communication(0, 0)
        raise AssertionError()
    except ValueError:
        pass

    try:
        strategy.disconnect_nodes(0, 0)
        raise AssertionError()
    except ValueError:
        pass

    try:
        strategy.connect_nodes(1, 1)
        raise AssertionError()
    except ValueError:
        pass


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_reset_communications(mock_init_configs):
    """Test whether Strategy attributes resets communication matrix correctly when reset_communications is called."""
    strategy = RandomFuzzer(iteration_type=Mock())
    mock_init_configs.assert_called_once()
    strategy.update_network([node_0, node_1, node_2])
    strategy.partition_network([[0], [1, 2]])
    strategy.reset_communications()
    assert strategy.communication_matrix == [
        [False, True, True],
        [True, False, True],
        [True, True, False],
    ]


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_partition_network_0(mock_init_configs):
    """Test whether Strategy attributes get updated correctly when partition_network is called. Formation 0."""
    strategy = RandomFuzzer(iteration_type=Mock())
    mock_init_configs.assert_called_once()
    strategy.update_network([node_0, node_1, node_2])
    strategy.partition_network([[0], [1, 2]])
    assert strategy.communication_matrix == [
        [False, False, False],
        [False, False, True],
        [False, True, False],
    ]


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_partition_network_1(mock_init_configs):
    """Test whether Strategy attributes get updated correctly when partition_network is called. Formation 1."""
    strategy = RandomFuzzer(iteration_type=Mock())
    mock_init_configs.assert_called_once()

    strategy.update_network([node_0, node_1, node_2])
    strategy.partition_network([[0, 1, 2]])
    assert strategy.communication_matrix == [
        [False, True, True],
        [True, False, True],
        [True, True, False],
    ]


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_partition_network_2(mock_init_configs):
    """Test whether Strategy attributes get updated correctly when partition_network is called."""
    strategy = RandomFuzzer(iteration_type=Mock())
    mock_init_configs.assert_called_once()

    strategy.update_network([node_0, node_1, node_2])
    strategy.partition_network([[0], [1], [2]])
    assert strategy.communication_matrix == [
        [False, False, False],
        [False, False, False],
        [False, False, False],
    ]


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_partition_network_invalid_partitions(mock_init_configs):
    """Test whether invalid partitions get rejected. Missing port."""
    strategy = RandomFuzzer(iteration_type=Mock())
    mock_init_configs.assert_called_once()
    strategy.update_network([node_0, node_1, node_2])
    try:
        strategy.partition_network([[0], [2]])
        raise AssertionError()
    except ValueError:
        pass


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_partition_network_invalid_amount(mock_init_configs):
    """Test whether invalid partitions get rejected. Duplicated port."""
    strategy = RandomFuzzer(iteration_type=Mock())
    mock_init_configs.assert_called_once()
    strategy.update_network([node_0, node_1, node_2])
    try:
        strategy.partition_network([[0], [1, 1, 2]])
        raise AssertionError()
    except ValueError:
        pass


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_apply_partition(mock_init_configs):
    """Test whether partitions get applied correctly."""
    strategy = RandomFuzzer(iteration_type=Mock())
    mock_init_configs.assert_called_once()
    strategy.update_network([node_0, node_1, node_2])
    strategy.partition_network([[0, 1], [2]])
    assert strategy.check_communication(0, 1)
    assert strategy.check_communication(0, 1)
    assert not strategy.check_communication(0, 2)
    assert not strategy.check_communication(2, 0)
    assert not strategy.check_communication(1, 2)

    # Test whether exception gets raised when ports are equal
    try:
        assert not strategy.check_communication(2, 2)
        raise AssertionError()
    except ValueError:
        pass

    assert strategy.check_communication(1, 0)
