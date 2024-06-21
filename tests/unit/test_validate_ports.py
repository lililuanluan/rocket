"""Test validate_ports function."""

import pytest

from xrpl_controller.core import validate_ports_or_ids


def test_validate_ports():
    """Test validate_ports function."""
    assert validate_ports_or_ids(10, 11) is None
    assert validate_ports_or_ids(0, 1) is None

    with pytest.raises(ValueError):
        validate_ports_or_ids(-1, 100)

    with pytest.raises(ValueError):
        validate_ports_or_ids(0, -1)

    with pytest.raises(ValueError):
        validate_ports_or_ids(60000, 60000)
