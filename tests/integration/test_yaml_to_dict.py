"""Tests for yaml_to_dict method in core.py."""

from xrpl_controller.core import yaml_to_dict

test_dir = "./tests/test_configs/yaml_to_dict/"


def test_yaml_to_dict():
    """Test yaml_to_dict method."""
    # create_test_config("TEST_YAML_DICT1", {"test": 2})
    # create_test_config("TEST_YAML_DICT2", None)
    # create_test_config("TEST_YAML_DICT3", {"test3": [[1, 2, 3]]})
    assert yaml_to_dict("TEST_YAML_DICT2", test_dir) == {}
    assert yaml_to_dict("TEST_YAML_DICT1", test_dir) == {"test": 2}
    assert yaml_to_dict("TEST_YAML_DICT1.yaml", test_dir) == {"test": 2}

    assert yaml_to_dict("TEST_YAML_DICT3", test_dir) == {"test3": [[1, 2, 3]]}


# def create_test_config(filename, cfg):
#     """Create test config file."""
#     Path(test_dir).mkdir(
#         parents=True, exist_ok=True
#     )
#
#     with open(test_dir + filename + ".yaml", "w") as f:
#         if cfg is not None:
#             yaml.dump(cfg, f)
