"""Test the functionality which automatically parses identical subsequent messages."""

from tests.test_strategy import node_0, node_1, node_2
from xrpl_controller.strategies import RandomFuzzer

# Ports of the imported nodes are 10, 11, 12 respectively


def test_auto_parsing():
    """Test the automatic parsing of identical subsequent messages."""
    strategy = RandomFuzzer(0, 0, 0, 150)
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
