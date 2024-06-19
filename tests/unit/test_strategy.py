"""Tests for Strategy class."""

from encodings.utf_8 import encode
from unittest.mock import patch

from protos import packet_pb2
from xrpl_controller.core import MAX_U32
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

node_3 = ValidatorNode(
    SocketAddress("test_peer", 13),
    SocketAddress("test-ws-pub", 23),
    SocketAddress("test-ws-adm", 33),
    SocketAddress("test-rpc", 43),
    ValidatorKeyData("status", "key", "K3Y", "PUB", "T3ST"),
)

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


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_init(mock_init_configs):
    """Test whether Strategy attributes get initialized correctly."""
    strategy = RandomFuzzer()
    mock_init_configs.assert_called_once()
    assert strategy.validator_node_list == []
    assert strategy.public_to_private_key_map == {}
    assert strategy.node_amount == 0
    assert strategy.port_to_id_dict == {}
    assert strategy.communication_matrix == []
    assert strategy.auto_partition
    assert strategy.auto_parse_identical
    assert strategy.prev_message_action_matrix == []
    assert strategy.keep_action_log


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_update_network(mock_init_configs):
    """Test whether Strategy attributes get updated correctly with update_network function."""
    strategy = RandomFuzzer()
    mock_init_configs.assert_called_once()
    strategy.update_network([node_0, node_1, node_2])
    assert strategy.validator_node_list == [node_0, node_1, node_2]
    assert strategy.node_amount == 3
    assert strategy.port_dict == {10: 0, 11: 1, 12: 2}
    assert strategy.id_dict == {0: 10, 1: 11, 2: 12}
    assert strategy.id_to_port(2) == 12
    assert strategy.port_to_id(12) == 2
    assert strategy.communication_matrix == [
        [False, True, True],
        [True, False, True],
        [True, True, False],
    ]

    assert strategy.subsets_dict == {0: [], 1: [], 2: []}

    assert len(strategy.prev_message_action_matrix) == 3
    for row in strategy.prev_message_action_matrix:
        assert len(row) == 3
        for item in row:
            assert item.initial_message == b""
            assert item.final_message == b""
            assert item.action == -1


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_process_message(mock_init_configs):
    """Test for process_message function."""
    strategy = RandomFuzzer()
    mock_init_configs.assert_called_once()

    strategy.update_network([node_0, node_1, node_2])
    packet_ack = packet_pb2.Packet(data=b"test", from_port=10, to_port=11)
    assert strategy.process_packet(packet_ack) == (b"test", 119)

    # Check whether action differs from previous one, could be flaky, but we used a seed
    packet_ack = packet_pb2.Packet(data=b"test2", from_port=10, to_port=11)
    assert strategy.process_packet(packet_ack) == (b"test2", 13)

    # Check whether set_message gets modified
    assert strategy.prev_message_action_matrix[0][1].initial_message == b"test2"
    assert strategy.prev_message_action_matrix[0][1].action == 13
    assert strategy.prev_message_action_matrix[0][1].final_message == b"test2"

    # Check whether messages get dropped automatically through auto partition
    strategy.partition_network([[0, 1], [2]])
    for i in range(100):
        msg = encode("test" + str(i))[0]  # Just arbitrary encoding
        packet_ack = packet_pb2.Packet(data=msg, from_port=10, to_port=12)
        assert strategy.process_packet(packet_ack) == (msg, MAX_U32)

    # Check whether result will always stay the same with auto parse identical messages
    packet_ack = packet_pb2.Packet(data=b"test", from_port=10, to_port=12)
    result = strategy.process_packet(packet_ack)
    for _ in range(100):
        packet_ack = packet_pb2.Packet(data=b"test", from_port=10, to_port=12)
        assert strategy.process_packet(packet_ack) == result
