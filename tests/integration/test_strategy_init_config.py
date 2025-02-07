"""Test strategy initialization, integrated test."""

from unittest.mock import Mock

from rocket_controller.strategies import RandomFuzzer


def test_strategy_init():
    """Test whether Strategy attributes get initialized correctly."""
    strategy = RandomFuzzer(
        strategy_config_path="./tests/_configs/random_fuzzer/TEST_INIT.yaml",
        iteration_type=Mock(),
    )
    assert strategy.params == {
        "delay_probability": 0.1,
        "drop_probability": 0.1,
        "min_delay_ms": 10,
        "max_delay_ms": 150,
        "seed": 42,
        "send_probability": 0.8,
    }
