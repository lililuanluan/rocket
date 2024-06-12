"""Tests the ValidatorKeyData class."""

from xrpl_controller.validator_node_info import ValidatorKeyData


def test_constructor():
    """Test the constructor."""
    key_data = ValidatorKeyData(
        "status", "val_key", "val_prv_key", "val_pub_key", "val_seed"
    )
    assert key_data.status == "status"
    assert key_data.validation_key == "val_key"
    assert key_data.validation_private_key == "val_prv_key"
    assert key_data.validation_public_key == "val_pub_key"
    assert key_data.validation_seed == "val_seed"


def test_to_string():
    """Test the __str__ method of the ValidatorKeyData class."""
    key_data = ValidatorKeyData(
        "status", "val_key", "val_prv_key", "val_pub_key", "val_seed"
    )
    assert key_data.__str__() == (
        "ValidatorKeyData(status=status, validation_key=val_key, "
        "validation_private_key=val_prv_key, validation_public_key=val_pub_key, "
        "validation_seed=val_seed)"
    )
