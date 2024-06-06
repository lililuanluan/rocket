"""Tests for Strategy class."""

from xrpl_controller.strategies import RandomFuzzer
from xrpl_controller.validator_node_info import (
    SocketAddress,
    ValidatorKeyData,
    ValidatorNode,
)

node_0 = ValidatorNode(
    SocketAddress("test_peer", 10),
    SocketAddress("test-ws-pub", 20),
    SocketAddress("test-ws-adm", 30),
    SocketAddress("test-rpc", 40),
    ValidatorKeyData("status", "key", "K3Y", "PUB", "T3ST"),
)

node_1 = ValidatorNode(
    SocketAddress("test_peer", 11),
    SocketAddress("test-ws-pub", 21),
    SocketAddress("test-ws-adm", 31),
    SocketAddress("test-rpc", 41),
    ValidatorKeyData("status", "key", "K3Y", "PUB", "T3ST"),
)

node_2 = ValidatorNode(
    SocketAddress("test_peer", 12),
    SocketAddress("test-ws-pub", 22),
    SocketAddress("test-ws-adm", 32),
    SocketAddress("test-rpc", 42),
    ValidatorKeyData("status", "key", "K3Y", "PUB", "T3ST"),
)


def test_init():
    """Test whether Strategy attributes get initialized correctly."""
    strategy = RandomFuzzer(0.1, 0.1, 10, 150, 10)
    assert strategy.validator_node_list == []
    assert strategy.node_amount == 0
    assert strategy.port_dict == {}
    assert strategy.communication_matrix == []
    assert strategy.auto_partition
    assert strategy.auto_parse
    assert strategy.prev_message_action_matrix == []


def test_update_network():
    """Test whether Strategy attributes get updated correctly with update_network function."""
    strategy = RandomFuzzer(0.1, 0.1, 10, 150, 10)
    strategy.update_network([node_0, node_1, node_2])
    assert strategy.validator_node_list == [node_0, node_1, node_2]
    assert strategy.node_amount == 3
    assert strategy.port_dict == {10: 0, 11: 1, 12: 2}
    assert strategy.communication_matrix == [
        [False, True, True],
        [True, False, True],
        [True, True, False],
    ]

    assert len(strategy.prev_message_action_matrix) == 3
    for row in strategy.prev_message_action_matrix:
        assert len(row) == 3
        for item in row:
            assert item.initial_message == b""
            assert item.final_message == b""
            assert item.action == -1
