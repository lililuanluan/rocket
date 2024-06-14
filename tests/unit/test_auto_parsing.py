"""Test the functionality which automatically parses identical subsequent messages."""

from protos import packet_pb2
from tests.unit.test_strategy import node_0, node_1, node_2
from xrpl_controller.strategies import RandomFuzzer

# Ports of the imported nodes are 10, 11, 12 respectively


def test_auto_parsing():
    """Test the automatic parsing of identical subsequent messages."""
    strategy = RandomFuzzer()
    strategy.update_network([node_0, node_1, node_2])
    strategy.set_message_action(10, 11, b"test", b"mutated", 42)
    res = strategy.check_previous_message(10, 11, b"notest")
    assert not res[0]
    assert res[1] == (b"mutated", 42)

    res2 = strategy.check_previous_message(10, 11, b"test")
    assert res2[0]
    assert res2[1] == (b"mutated", 42)

    res3 = strategy.check_previous_message(10, 12, b"test")
    assert not res3[0]
    assert res3[1] == (b"", -1)

    try:
        strategy.set_message_action(10, 10, b"test", b"mutated", 42)
        raise AssertionError()
    except ValueError:
        pass


def test_auto_parsing_false():
    """Test whether attributes do not get saved when boolean is false."""
    strategy = RandomFuzzer(auto_parse_identical=False)
    assert not hasattr(strategy, "prev_message_action_matrix")

    strategy.update_network([node_0, node_1, node_2])
    assert not hasattr(strategy, "prev_message_action_matrix")

    # Following 2 calls should throw an assertion errors, so this is a work-around
    try:
        strategy.set_message_action(10, 11, b"test", b"mutated", 42)
        raise ValueError()
    except AssertionError:
        pass
    except ValueError():
        raise AssertionError() from None

    try:
        strategy.check_previous_message(10, 11, b"test")
        raise ValueError()
    except AssertionError:
        pass
    except ValueError():
        raise AssertionError() from None

    packet_ack = packet_pb2.Packet(data=b"test", from_port=10, to_port=11)
    strategy.process_packet(packet_ack)
    assert not hasattr(strategy, "prev_message_action_matrix")
