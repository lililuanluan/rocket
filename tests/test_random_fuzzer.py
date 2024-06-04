"""Tests for the RandomFuzzer class."""

from protos import packet_pb2
from xrpl_controller.strategies import RandomFuzzer


def test_init():
    """Tests whether the RandomFuzzer object is initialized correctly."""
    fuzzer = RandomFuzzer(0.1, 0.1, 10, 150)
    assert fuzzer.drop_probability == 0.1
    assert fuzzer.delay_probability == 0.1
    assert fuzzer.min_delay_ms == 10
    assert fuzzer.max_delay_ms == 150

    # Make sure super().__init__() is called
    assert fuzzer.node_amount == 0


def test_init_bound_0():
    """Test whether values on the bounds still pass."""
    fuzzer = RandomFuzzer(0.4, 0.6, 10, 150)
    assert fuzzer.drop_probability == 0.4
    assert fuzzer.delay_probability == 0.6
    assert fuzzer.min_delay_ms == 10
    assert fuzzer.max_delay_ms == 150


def test_init_bound_1():
    """Test whether values on the bounds still pass."""
    fuzzer = RandomFuzzer(0, 0, 0, 0)
    assert fuzzer.drop_probability == 0
    assert fuzzer.delay_probability == 0
    assert fuzzer.min_delay_ms == 0
    assert fuzzer.max_delay_ms == 0


def test_init_invalid_sum_0():
    """Test whether probabilities sum to at most 1."""
    try:
        RandomFuzzer(0.4, 0.61, 0, 0)
        raise AssertionError()
    except ValueError:
        pass


def test_init_invalid_sum_1():
    """Test whether probabilities sum to at most 1. Overflow caused by drop_probability."""
    try:
        RandomFuzzer(1.001, 0, 0, 0)
        raise AssertionError()
    except ValueError:
        pass


def test_init_invalid_sum_2():
    """Test whether probabilities sum to at most 1. Overflow caused by delay_probability."""
    try:
        RandomFuzzer(0, 2.0, 0, 0)
        raise AssertionError()
    except ValueError:
        pass


def test_init_negative_drop():
    """Test whether drop probability is non-negative."""
    try:
        RandomFuzzer(-0.001, 0.5, 0, 0)
        raise AssertionError()
    except ValueError:
        pass


def test_init_negative_delay():
    """Test whether delay probability is non-negative."""
    try:
        RandomFuzzer(0.5, -1, 0, 0)
        raise AssertionError()
    except ValueError:
        pass


def test_init_negative_min_delay():
    """Test whether min_delay_ms is non-negative."""
    try:
        RandomFuzzer(0.5, 0.3, -1, 150)
        raise AssertionError()
    except ValueError:
        pass


def test_init_negative_max_delay():
    """Test whether max_delay_ms is non-negative."""
    try:
        RandomFuzzer(0.5, 0.3, 1, -1)
        raise AssertionError()
    except ValueError:
        pass


def test_init_invalid_range():
    """Test whether min_delay_ms is not greater than max_delay_ms."""
    try:
        RandomFuzzer(0.5, 0.3, 2, 1)
        raise AssertionError()
    except ValueError:
        pass


def test_handle_packet():
    """Test the handle_packet method with a random seed."""
    fuzzer = RandomFuzzer(0.33, 0.33, 10, 150, 10)
    packet_ack = packet_pb2.PacketAck(
        data=b"test",
        action=4294967295,
    )

    assert fuzzer.handle_packet(packet_ack) == (b"test", 4294967295)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 4294967295)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 4294967295)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 0)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 81)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 4294967295)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 0)
