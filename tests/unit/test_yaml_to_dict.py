"""Tests for yaml_to_dict method in core.py."""

import os
from pathlib import Path

import yaml

from xrpl_controller.core import yaml_to_dict


def test_yaml_to_dict():
    """Test yaml_to_dict method."""
    create_test_config("TEST_YAML_DICT", {"test": 2})
    create_test_config("TEST_YAML_DICT2", None)
    create_test_config("TEST_YAML_DICT3", {"test3": [[1, 2, 3]]})

    assert (
        yaml_to_dict("TEST_YAML_DICT2", "./xrpl_controller/strategies/configs/") == {}
    )
    assert yaml_to_dict("TEST_YAML_DICT", "./xrpl_controller/strategies/configs/") == {
        "test": 2
    }
    assert yaml_to_dict(
        "TEST_YAML_DICT.yaml", "./xrpl_controller/strategies/configs"
    ) == {"test": 2}

    assert yaml_to_dict("TEST_YAML_DICT3", "./xrpl_controller/strategies/configs/") == {
        "test3": [[1, 2, 3]]
    }

    remove_test_config("TEST_YAML_DICT")
    remove_test_config("TEST_YAML_DICT2")
    remove_test_config("TEST_YAML_DICT3")


def create_test_config(filename, cfg):
    """Create test config file."""
    Path("xrpl_controller/xrpl_controller/strategies/configs").mkdir(
        parents=True, exist_ok=True
    )

    with open("./xrpl_controller/strategies/configs/" + filename + ".yaml", "w") as f:
        if cfg is not None:
            yaml.dump(cfg, f)


def remove_test_config(filename):
    """Remove test config file."""
    os.remove("./xrpl_controller/strategies/configs/" + filename + ".yaml")
