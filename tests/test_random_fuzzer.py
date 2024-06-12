"""Tests for the RandomFuzzer class."""

import json
import os
from pathlib import Path

from protos import packet_pb2
from xrpl_controller.strategies import RandomFuzzer


def test_init():
    """Tests whether the RandomFuzzer object is initialized correctly."""
    fn = "TEST_INIT"
    create_test_config(fn, 0.1, 0.1, 10, 150)
    fuzzer = RandomFuzzer(strategy_config_file=fn)
    assert fuzzer.params["drop_probability"] == 0.1
    assert fuzzer.params["delay_probability"] == 0.1
    assert fuzzer.params["min_delay_ms"] == 10
    assert fuzzer.params["max_delay_ms"] == 150

    # Make sure super().__init__() is called
    assert fuzzer.node_amount == 0
    remove_test_config(fn)


def test_init_bound_0():
    """Test whether values on the bounds still pass."""
    fn = "TEST_BOUND_0"
    create_test_config(fn, 0.4, 0.6, 10, 150)
    fuzzer = RandomFuzzer(strategy_config_file=fn)
    assert fuzzer.params["drop_probability"] == 0.4
    assert fuzzer.params["delay_probability"] == 0.6
    assert fuzzer.params["min_delay_ms"] == 10
    assert fuzzer.params["max_delay_ms"] == 150
    remove_test_config(fn)


def test_init_bound_1():
    """Test whether values on the bounds still pass."""
    fn = "TEST_BOUND_1"
    create_test_config(fn, 0, 0, 0, 0)
    fuzzer = RandomFuzzer(strategy_config_file=fn)
    assert fuzzer.params["drop_probability"] == 0
    assert fuzzer.params["delay_probability"] == 0
    assert fuzzer.params["min_delay_ms"] == 0
    assert fuzzer.params["max_delay_ms"] == 0
    remove_test_config(fn)


def test_init_invalid_sum_0():
    """Test whether probabilities sum to at most 1."""
    fn = "TEST_INV_SUM_0"
    create_test_config(fn, 0.4, 0.61, 0, 0)
    try:
        RandomFuzzer(strategy_config_file=fn)
        raise AssertionError()
    except ValueError:
        pass
    remove_test_config(fn)


def test_init_invalid_sum_1():
    """Test whether probabilities sum to at most 1. Overflow caused by drop_probability."""
    fn = "TEST_INV_SUM_1"
    create_test_config(fn, 1.001, 0, 0, 0)
    try:
        RandomFuzzer(strategy_config_file=fn)
        raise AssertionError()
    except ValueError:
        pass
    remove_test_config(fn)


def test_init_invalid_sum_2():
    """Test whether probabilities sum to at most 1. Overflow caused by delay_probability."""
    fn = "TEST_INV_SUM_2"
    create_test_config(fn, 0, 2.0, 0, 0)
    try:
        RandomFuzzer(strategy_config_file=fn)
        raise AssertionError()
    except ValueError:
        pass
    finally:
        remove_test_config(fn)


def test_init_negative_drop():
    """Test whether drop probability is non-negative."""
    fn = "TEST_N_DROP"
    create_test_config("TEST_N_DROP", -0.001, 0.5, 0, 0)
    try:
        RandomFuzzer(strategy_config_file=fn)
        raise AssertionError()
    except ValueError:
        pass
    finally:
        remove_test_config(fn)


def test_init_negative_delay():
    """Test whether delay probability is non-negative."""
    fn = "TEST_N_DELAY"
    create_test_config(fn, 0.5, -1, 0, 0)
    try:
        RandomFuzzer(strategy_config_file=fn)
        raise AssertionError()
    except ValueError:
        pass
    finally:
        remove_test_config(fn)


def test_init_negative_min_delay():
    """Test whether min_delay_ms is non-negative."""
    fn = "TEST_N_MIN_DELAY"
    create_test_config(fn, 0.5, 0.3, -1, 150)
    try:
        RandomFuzzer(strategy_config_file=fn)
        raise AssertionError()
    except ValueError:
        pass
    finally:
        remove_test_config(fn)


def test_init_negative_max_delay():
    """Test whether max_delay_ms is non-negative."""
    fn = "TEST_N_MAX_DELAY"
    create_test_config(fn, 0.5, 0.3, 1, -1)
    try:
        RandomFuzzer(strategy_config_file=fn)
        raise AssertionError()
    except ValueError:
        pass
    finally:
        remove_test_config(fn)


def test_init_invalid_range():
    """Test whether min_delay_ms is not greater than max_delay_ms."""
    fn = "TEST_INV_RANGE"
    create_test_config(fn, 0.5, 0.3, 2, 1)
    try:
        RandomFuzzer(strategy_config_file=fn)
        raise AssertionError()
    except ValueError:
        pass
    finally:
        remove_test_config(fn)


def test_handle_packet():
    """Test the handle_packet method with a random seed."""
    fn = "TEST_SEED"
    create_test_config(fn, 0.33, 0.33, 10, 150, 10)
    fuzzer = RandomFuzzer(strategy_config_file=fn)

    packet_ack = packet_pb2.Packet(data=b"test", from_port=60000, to_port=3)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 4294967295)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 4294967295)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 4294967295)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 0)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 81)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 4294967295)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 0)
    remove_test_config(fn)


def create_test_config(filename, drop_prob, delay_prob, min, max, seed=None):
    """Create test config file."""
    Path("./xrpl_controller/strategies/configs").mkdir(parents=True, exist_ok=True)

    cfg = {
        "drop_probability": drop_prob,
        "delay_probability": delay_prob,
        "min_delay_ms": min,
        "max_delay_ms": max,
        "seed": seed,
    }

    with open("./xrpl_controller/strategies/configs/" + filename + ".json", "w") as f:
        json.dump(cfg, f, indent=4)


def remove_test_config(filename):
    """Remove test config file."""
    os.remove("./xrpl_controller/strategies/configs/" + filename + ".json")
