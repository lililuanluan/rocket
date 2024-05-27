"""Tests for network partitions functionality."""

from xrpl_controller.strategies.random_fuzzer import RandomFuzzer
from xrpl_controller.validator_node_info import ValidatorNode
from xrpl_controller.validator_node_info import SocketAddress
from xrpl_controller.validator_node_info import ValidatorKeyData
from xrpl_controller.core import MAX_U32

node_0 = ValidatorNode(
    SocketAddress("test", 10),
    SocketAddress("test-ws", 10),
    SocketAddress("test-rpc", 10),
    ValidatorKeyData("status", "key", "K3Y", "PUB", "T3ST"),
)

node_1 = ValidatorNode(
    SocketAddress("test", 11),
    SocketAddress("test-ws", 11),
    SocketAddress("test-rpc", 11),
    ValidatorKeyData("status", "key", "K3Y", "PUB", "T3ST"),
)

node_2 = ValidatorNode(
    SocketAddress("test", 12),
    SocketAddress("test-ws", 12),
    SocketAddress("test-rpc", 12),
    ValidatorKeyData("status", "key", "K3Y", "PUB", "T3ST"),
)


def test_init():
    """Test whether Strategy attributes get initialized correctly."""
    strategy = RandomFuzzer(0.1, 0.1, 10, 150, 10)
    assert strategy.validator_node_list == []
    assert strategy.node_amount == 0
    assert strategy.network_partitions == []
    assert strategy.port_dict == {}
    assert strategy.communication_matrix == []
    assert strategy.auto_partition


def test_update_network():
    """Test whether Strategy attributes get updated correctly with update_network function."""
    strategy = RandomFuzzer(0.1, 0.1, 10, 150, 10)
    strategy.update_network([node_0, node_1, node_2])
    assert strategy.validator_node_list == [node_0, node_1, node_2]
    assert strategy.node_amount == 3
    assert strategy.network_partitions == [[10, 11, 12]]
    assert strategy.port_dict == {10: 0, 11: 1, 12: 2}
    assert strategy.communication_matrix == [
        [True, True, True],
        [True, True, True],
        [True, True, True],
    ]


def test_partition_network_0():
    """Test whether Strategy attributes get updated correctly when partition_network is called. Formation 0."""
    strategy = RandomFuzzer(0.1, 0.1, 10, 150, 10)
    strategy.update_network([node_0, node_1, node_2])
    strategy.partition_network([[10], [11, 12]])
    assert strategy.network_partitions == [[10], [11, 12]]
    assert strategy.communication_matrix == [
        [True, False, False],
        [False, True, True],
        [False, True, True],
    ]


def test_partition_network_1():
    """Test whether Strategy attributes get updated correctly when partition_network is called. Formation 1."""
    strategy = RandomFuzzer(0.1, 0.1, 10, 150, 10)
    strategy.update_network([node_0, node_1, node_2])
    strategy.partition_network([[10, 11, 12]])
    assert strategy.network_partitions == [[10, 11, 12]]
    assert strategy.communication_matrix == [
        [True, True, True],
        [True, True, True],
        [True, True, True],
    ]


def test_partition_network_2():
    """Test whether Strategy attributes get updated correctly when partition_network is called."""
    strategy = RandomFuzzer(0.1, 0.1, 10, 150, 10)
    strategy.update_network([node_0, node_1, node_2])
    strategy.partition_network([[10], [11], [12]])
    assert strategy.network_partitions == [[10], [11], [12]]
    assert strategy.communication_matrix == [
        [True, False, False],
        [False, True, False],
        [False, False, True],
    ]


def test_partition_network_invalid_partitions():
    """Test whether invalid partitions get rejected. Missing port."""
    strategy = RandomFuzzer(0.1, 0.1, 10, 150, 10)
    strategy.update_network([node_0, node_1, node_2])
    try:
        strategy.partition_network([[10], [12]])
        assert False
    except ValueError:
        pass


def test_partition_network_invalid_amount():
    """Test whether invalid partitions get rejected. Duplicated port."""
    strategy = RandomFuzzer(0.1, 0.1, 10, 150, 10)
    strategy.update_network([node_0, node_1, node_2])
    try:
        strategy.partition_network([[10], [11, 11, 12]])
        assert False
    except ValueError:
        pass


def test_apply_partition():
    """Test whether partitions get applied correctly."""
    strategy = RandomFuzzer(0.1, 0.1, 10, 150, 10)
    strategy.update_network([node_0, node_1, node_2])
    strategy.partition_network([[10, 11], [12]])
    assert strategy.apply_network_partition(0, 10, 11) == 0
    assert strategy.apply_network_partition(42, 10, 11) == 42
    assert strategy.apply_network_partition(0, 10, 12) == MAX_U32
    assert strategy.apply_network_partition(0, 12, 10) == MAX_U32
    assert strategy.apply_network_partition(42, 11, 12) == MAX_U32
    assert strategy.apply_network_partition(42, 12, 12) == 42
