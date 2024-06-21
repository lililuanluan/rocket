"""Test the functionality which automatically parses identical subsequent messages."""

from unittest.mock import Mock, patch

import pytest

from protos import packet_pb2
from tests.variable_store import node_0, node_1, node_2, node_3
from xrpl_controller.network_manager import NetworkManager
from xrpl_controller.strategies import RandomFuzzer

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


def test_auto_parsing():
    """Test the automatic parsing of identical subsequent messages."""
    network = NetworkManager()

    network.update_network([node_0, node_1, node_2])
    network.set_message_action(0, 1, b"test", b"mutated", 42)
    res = network.check_previous_message(0, 1, b"notest")
    assert not res[0]
    assert res[1] == (b"mutated", 42)

    res2 = network.check_previous_message(0, 1, b"test")
    assert res2[0]
    assert res2[1] == (b"mutated", 42)

    res3 = network.check_previous_message(0, 2, b"test")
    assert not res3[0]
    assert res3[1] == (b"", -1)

    with pytest.raises(ValueError):
        network.set_message_action(0, 0, b"test", b"mutated", 42)


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_auto_parsing_false(mock_init_configs):
    """Test whether attributes do not get saved when boolean is false."""
    strategy = RandomFuzzer(
        auto_parse_identical=False, auto_parse_subsets=False, iteration_type=Mock()
    )
    mock_init_configs.assert_called_once()

    strategy.update_network([node_0, node_1, node_2])

    with pytest.raises(ValueError):
        strategy.network.set_message_action(0, 1, b"test", b"mutated", 42)

    with pytest.raises(ValueError):
        strategy.network.check_previous_message(0, 1, b"test")

    packet_ack = packet_pb2.Packet(data=b"testtest", from_port=10, to_port=11)
    strategy.process_packet(packet_ack)


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_auto_parsing_subsets(mock_init_configs):
    """Test auto parsing subsets functionality."""
    strategy = RandomFuzzer(iteration_type=Mock())
    mock_init_configs.assert_called_once()
    strategy.update_network([node_0, node_1, node_2])

    # Node 2 will sends same messages to node 0 and node 1 if possible
    strategy.network.set_subsets_dict({2: [0, 1]})
    assert strategy.network.subsets_dict == {0: [], 1: [], 2: [0, 1]}
    strategy.network.set_message_action(2, 0, b"testtest", b"mutated", 42)
    assert strategy.network.check_subsets(2, 1, b"testtest") == (True, (b"mutated", 42))
    assert strategy.network.check_subsets(2, 1, b"testtest2") == (
        False,
        (b"mutated", 42),
    )

    # Entry is now wrapped in another list
    strategy.network.set_subsets_dict({2: [[0, 1]]})
    assert strategy.network.subsets_dict == {0: [], 1: [], 2: [[0, 1]]}
    strategy.network.set_message_action(2, 0, b"testtest2", b"mutated", 42)
    assert strategy.network.check_subsets(2, 1, b"testtest2") == (
        True,
        (b"mutated", 42),
    )
    assert strategy.network.check_subsets(2, 1, b"testtestF") == (
        False,
        (b"mutated", 42),
    )

    packet_ack = packet_pb2.Packet(data=b"testtest", from_port=10, to_port=11)
    strategy.process_packet(packet_ack)


def test_auto_parsing_subsets_4_nodes():
    """Test edge cases where there are multiple subsets to be checked."""
    network = NetworkManager()
    network.update_network([node_0, node_1, node_2, node_3])
    network.set_subsets_dict({2: [[0], [1, 3]]})
    assert network.subsets_dict == {0: [], 1: [], 2: [[0], [1, 3]], 3: []}

    network.set_message_action(2, 0, b"testtest", b"mutated", 42)
    network.set_message_action(2, 1, b"testtest", b"mutated2", 42)
    assert network.check_subsets(2, 3, b"testtest") == (True, (b"mutated2", 42))


def test_raises():
    """Test whether exceptions get raised."""
    network = NetworkManager(auto_parse_identical=False, auto_parse_subsets=False)

    with pytest.raises(ValueError):
        network.set_message_action(0, 1, b"testtest", b"mutated", 42)

    with pytest.raises(ValueError):
        network.set_subsets_dict({})

    with pytest.raises(ValueError):
        network.set_subsets_dict_entry(2, [0, 1])

    with pytest.raises(ValueError):
        network.check_subsets(2, 1, b"testtest")
