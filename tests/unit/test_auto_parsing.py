"""Test the functionality which automatically parses identical subsequent messages."""

from unittest.mock import Mock

import pytest

from protos import packet_pb2
from tests.unit.test_strategy import node_0, node_1, node_2, node_3
from xrpl_controller.strategies import RandomFuzzer

# Ports of the imported nodes are 10, 11, 12, 13 respectively


def test_auto_parsing():
    """Test the automatic parsing of identical subsequent messages."""
    strategy = RandomFuzzer(iteration_type=Mock())
    strategy.update_network([node_0, node_1, node_2])
    strategy.set_message_action(0, 1, b"test", b"mutated", 42)
    res = strategy.check_previous_message(0, 1, b"notest")
    assert not res[0]
    assert res[1] == (b"mutated", 42)

    res2 = strategy.check_previous_message(0, 1, b"test")
    assert res2[0]
    assert res2[1] == (b"mutated", 42)

    res3 = strategy.check_previous_message(0, 2, b"test")
    assert not res3[0]
    assert res3[1] == (b"", -1)

    with pytest.raises(ValueError):
        strategy.set_message_action(0, 0, b"test", b"mutated", 42)


def test_auto_parsing_false():
    """Test whether attributes do not get saved when boolean is false."""
    strategy = RandomFuzzer(
        auto_parse_identical=False, auto_parse_subsets=False, iteration_type=Mock()
    )

    strategy.update_network([node_0, node_1, node_2])

    with pytest.raises(ValueError):
        strategy.set_message_action(0, 1, b"test", b"mutated", 42)

    with pytest.raises(ValueError):
        strategy.check_previous_message(0, 1, b"test")

    packet_ack = packet_pb2.Packet(data=b"testtest", from_port=10, to_port=11)
    strategy.process_packet(packet_ack)


def test_auto_parsing_subsets():
    """Test auto parsing subsets functionality."""
    strategy = RandomFuzzer(iteration_type=Mock())
    strategy.update_network([node_0, node_1, node_2])

    # Node 2 will sends same messages to node 0 and node 1 if possible
    strategy.set_subsets_dict({2: [0, 1]})
    assert strategy.subsets_dict == {0: [], 1: [], 2: [0, 1]}
    strategy.set_message_action(2, 0, b"testtest", b"mutated", 42)
    assert strategy.check_subsets(2, 1, b"testtest") == (True, (b"mutated", 42))
    assert strategy.check_subsets(2, 1, b"testtest2") == (False, (b"mutated", 42))

    # Entry is now wrapped in another list
    strategy.set_subsets_dict({2: [[0, 1]]})
    assert strategy.subsets_dict == {0: [], 1: [], 2: [[0, 1]]}
    strategy.set_message_action(2, 0, b"testtest2", b"mutated", 42)
    assert strategy.check_subsets(2, 1, b"testtest2") == (True, (b"mutated", 42))
    assert strategy.check_subsets(2, 1, b"testtestF") == (False, (b"mutated", 42))

    packet_ack = packet_pb2.Packet(data=b"testtest", from_port=10, to_port=11)
    strategy.process_packet(packet_ack)


def test_auto_parsing_subsets_4_nodes():
    """Test edge cases where there are multiple subsets to be checked."""
    strategy = RandomFuzzer(iteration_type=Mock())
    strategy.update_network([node_0, node_1, node_2, node_3])
    strategy.set_subsets_dict({2: [[0], [1, 3]]})
    assert strategy.subsets_dict == {0: [], 1: [], 2: [[0], [1, 3]], 3: []}

    strategy.set_message_action(2, 0, b"testtest", b"mutated", 42)
    strategy.set_message_action(2, 1, b"testtest", b"mutated2", 42)
    assert strategy.check_subsets(2, 3, b"testtest") == (True, (b"mutated2", 42))


def test_raises():
    """Test whether exceptions get raised."""
    strategy = RandomFuzzer(
        auto_parse_identical=False, auto_parse_subsets=False, iteration_type=Mock()
    )

    with pytest.raises(ValueError):
        strategy.set_message_action(0, 1, b"testtest", b"mutated", 42)

    with pytest.raises(ValueError):
        strategy.set_subsets_dict({})

    with pytest.raises(ValueError):
        strategy.set_subsets_dict_entry(2, [0, 1])

    with pytest.raises(ValueError):
        strategy.check_subsets(2, 1, b"testtest")
