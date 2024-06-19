"""Tests for the RandomFuzzer class."""

from unittest.mock import Mock, patch

import pytest

from protos import packet_pb2
from xrpl_controller.strategies import RandomFuzzer


@patch("xrpl_controller.strategies.random_fuzzer.Strategy.__init__", return_value=None)
@patch("xrpl_controller.strategies.random_fuzzer.RandomFuzzer.params", create=True)
def test_init(mock_params, mock_super_init):
    """Tests whether the RandomFuzzer object is initialized correctly."""
    mock_params.__getitem__.side_effect = {
        "delay_probability": 0.1,
        "drop_probability": 0.1,
        "min_delay_ms": 10,
        "max_delay_ms": 150,
        "seed": None,
    }.__getitem__

    fuzzer = RandomFuzzer(iteration_type=Mock())
    assert fuzzer.params["drop_probability"] == 0.1
    assert fuzzer.params["delay_probability"] == 0.1
    assert fuzzer.params["min_delay_ms"] == 10
    assert fuzzer.params["max_delay_ms"] == 150
    mock_super_init.assert_called_once()


@patch("xrpl_controller.strategies.random_fuzzer.Strategy.__init__", return_value=None)
@patch("xrpl_controller.strategies.random_fuzzer.RandomFuzzer.params", create=True)
def test_init_bound_0(mock_params, mock_super_init):
    """Test whether values on the bounds still pass."""
    mock_params.__getitem__.side_effect = {
        "delay_probability": 0.6,
        "drop_probability": 0.4,
        "min_delay_ms": 10,
        "max_delay_ms": 150,
        "seed": None,
    }.__getitem__
    fuzzer = RandomFuzzer(iteration_type=Mock())
    assert fuzzer.params["drop_probability"] == 0.4
    assert fuzzer.params["delay_probability"] == 0.6
    assert fuzzer.params["min_delay_ms"] == 10
    assert fuzzer.params["max_delay_ms"] == 150
    mock_super_init.assert_called_once()


@patch("xrpl_controller.strategies.random_fuzzer.Strategy.__init__", return_value=None)
@patch("xrpl_controller.strategies.random_fuzzer.RandomFuzzer.params", create=True)
def test_init_bound_1(mock_params, mock_super_init):
    """Test whether values on the bounds still pass."""
    mock_params.__getitem__.side_effect = {
        "delay_probability": 0,
        "drop_probability": 0,
        "min_delay_ms": 0,
        "max_delay_ms": 0,
        "seed": None,
    }.__getitem__
    fuzzer = RandomFuzzer(iteration_type=Mock())
    assert fuzzer.params["drop_probability"] == 0
    assert fuzzer.params["delay_probability"] == 0
    assert fuzzer.params["min_delay_ms"] == 0
    assert fuzzer.params["max_delay_ms"] == 0
    mock_super_init.assert_called_once()


@patch("xrpl_controller.strategies.random_fuzzer.Strategy.__init__", return_value=None)
@patch("xrpl_controller.strategies.random_fuzzer.RandomFuzzer.params", create=True)
def test_init_invalid_sum_0(mock_params, mock_super_init):
    """Test whether probabilities sum to at most 1."""
    mock_params.__getitem__.side_effect = {
        "delay_probability": 0.61,
        "drop_probability": 0.4,
        "min_delay_ms": 10,
        "max_delay_ms": 150,
        "seed": None,
    }.__getitem__

    with pytest.raises(ValueError, match="must sum to less than or equal to 1.0"):
        RandomFuzzer(iteration_type=Mock())
    mock_super_init.assert_called_once()


@patch("xrpl_controller.strategies.random_fuzzer.Strategy.__init__", return_value=None)
@patch("xrpl_controller.strategies.random_fuzzer.RandomFuzzer.params", create=True)
def test_init_invalid_sum_1(mock_params, mock_super_init):
    """Test whether probabilities sum to at most 1. Overflow caused by drop_probability."""
    mock_params.__getitem__.side_effect = {
        "delay_probability": 0,
        "drop_probability": 1.001,
        "min_delay_ms": 0,
        "max_delay_ms": 0,
        "seed": None,
    }.__getitem__

    with pytest.raises(ValueError, match="must sum to less than or equal to 1.0"):
        RandomFuzzer(iteration_type=Mock())
    mock_super_init.assert_called_once()


@patch("xrpl_controller.strategies.random_fuzzer.Strategy.__init__", return_value=None)
@patch("xrpl_controller.strategies.random_fuzzer.RandomFuzzer.params", create=True)
def test_init_invalid_sum_2(mock_params, mock_super_init):
    """Test whether probabilities sum to at most 1. Overflow caused by delay_probability."""
    mock_params.__getitem__.side_effect = {
        "delay_probability": 2.0,
        "drop_probability": 0,
        "min_delay_ms": 0,
        "max_delay_ms": 0,
        "seed": None,
    }.__getitem__

    with pytest.raises(ValueError, match="must sum to less than or equal to 1.0"):
        RandomFuzzer(iteration_type=Mock())
    mock_super_init.assert_called_once()


@patch("xrpl_controller.strategies.random_fuzzer.Strategy.__init__", return_value=None)
@patch("xrpl_controller.strategies.random_fuzzer.RandomFuzzer.params", create=True)
def test_init_negative_drop(mock_params, mock_super_init):
    """Test whether drop probability is non-negative."""
    mock_params.__getitem__.side_effect = {
        "delay_probability": 0.5,
        "drop_probability": -0.001,
        "min_delay_ms": 0,
        "max_delay_ms": 0,
        "seed": None,
    }.__getitem__

    with pytest.raises(
        ValueError, match="drop and delay probabilities must be non-negative"
    ):
        RandomFuzzer(iteration_type=Mock())
    mock_super_init.assert_called_once()


@patch("xrpl_controller.strategies.random_fuzzer.Strategy.__init__", return_value=None)
@patch("xrpl_controller.strategies.random_fuzzer.RandomFuzzer.params", create=True)
def test_init_negative_delay(mock_params, mock_super_init):
    """Test whether delay probability is non-negative."""
    mock_params.__getitem__.side_effect = {
        "delay_probability": -1,
        "drop_probability": 0.5,
        "min_delay_ms": 0,
        "max_delay_ms": 0,
        "seed": None,
    }.__getitem__

    with pytest.raises(
        ValueError, match="drop and delay probabilities must be non-negative"
    ):
        RandomFuzzer(iteration_type=Mock())
    mock_super_init.assert_called_once()


@patch("xrpl_controller.strategies.random_fuzzer.Strategy.__init__", return_value=None)
@patch("xrpl_controller.strategies.random_fuzzer.RandomFuzzer.params", create=True)
def test_init_negative_min_delay(mock_params, mock_super_init):
    """Test whether min_delay_ms is non-negative."""
    mock_params.__getitem__.side_effect = {
        "delay_probability": 0.3,
        "drop_probability": 0.5,
        "min_delay_ms": -1,
        "max_delay_ms": 150,
        "seed": None,
    }.__getitem__

    with pytest.raises(ValueError, match="delay values must both be non-negative"):
        RandomFuzzer(iteration_type=Mock())
    mock_super_init.assert_called_once()


@patch("xrpl_controller.strategies.random_fuzzer.Strategy.__init__", return_value=None)
@patch("xrpl_controller.strategies.random_fuzzer.RandomFuzzer.params", create=True)
def test_init_negative_max_delay(mock_params, mock_super_init):
    """Test whether max_delay_ms is non-negative."""
    mock_params.__getitem__.side_effect = {
        "delay_probability": 0.3,
        "drop_probability": 0.5,
        "min_delay_ms": 1,
        "max_delay_ms": -1,
        "seed": None,
    }.__getitem__

    with pytest.raises(ValueError, match="delay values must both be non-negative"):
        RandomFuzzer(iteration_type=Mock())
    mock_super_init.assert_called_once()


@patch("xrpl_controller.strategies.random_fuzzer.Strategy.__init__", return_value=None)
@patch("xrpl_controller.strategies.random_fuzzer.RandomFuzzer.params", create=True)
def test_init_invalid_range(mock_params, mock_super_init):
    """Test whether min_delay_ms is not greater than max_delay_ms."""
    mock_params.__getitem__.side_effect = {
        "delay_probability": 0.3,
        "drop_probability": 0.5,
        "min_delay_ms": 2,
        "max_delay_ms": 1,
        "seed": None,
    }.__getitem__

    with pytest.raises(
        ValueError, match="min_delay_ms must be smaller or equal to max_delay_ms"
    ):
        RandomFuzzer(iteration_type=Mock())
    mock_super_init.assert_called_once()


@patch("xrpl_controller.strategies.random_fuzzer.Strategy.__init__", return_value=None)
@patch("xrpl_controller.strategies.random_fuzzer.RandomFuzzer.params", create=True)
def test_handle_packet(mock_params, mock_super_init):
    """Test the handle_packet method with a random seed."""
    mock_params.__getitem__.side_effect = {
        "send_probability": 0.34,
        "delay_probability": 0.33,
        "drop_probability": 0.33,
        "min_delay_ms": 10,
        "max_delay_ms": 150,
        "seed": 10,
    }.__getitem__

    fuzzer = RandomFuzzer(iteration_type=Mock())
    mock_super_init.assert_called_once()
    packet_ack = packet_pb2.Packet(data=b"test", from_port=60000, to_port=3)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 4294967295)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 4294967295)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 4294967295)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 0)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 81)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 4294967295)
    assert fuzzer.handle_packet(packet_ack) == (b"test", 0)
