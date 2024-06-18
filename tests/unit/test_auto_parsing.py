"""Test the functionality which automatically parses identical subsequent messages."""

from unittest.mock import patch

from protos import packet_pb2
from tests.unit.test_strategy import node_0, node_1, node_2
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


# Ports of the imported nodes are 10, 11, 12 respectively
@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_auto_parsing(mock_init_configs):
    """Test the automatic parsing of identical subsequent messages."""
    strategy = RandomFuzzer()
    mock_init_configs.assert_called_once()
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


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_auto_parsing_false(mock_init_configs):
    """Test whether attributes do not get saved when boolean is false."""
    strategy = RandomFuzzer(auto_parse_identical=False)
    mock_init_configs.assert_called_once()
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
