"""Tests for yaml_to_dict method in core.py."""

from xrpl_controller.core import yaml_to_dict

test_dir = "./tests/test_configs/yaml_to_dict/"


def test_yaml_to_dict():
    """Test yaml_to_dict method."""
    assert yaml_to_dict(test_dir + "TEST_YAML_DICT2") == {}
    assert yaml_to_dict(test_dir + "TEST_YAML_DICT1") == {"test": 2}
    assert yaml_to_dict(test_dir + "TEST_YAML_DICT1.yaml") == {"test": 2}

    assert yaml_to_dict(test_dir + "TEST_YAML_DICT3") == {"test3": [[1, 2, 3]]}
