"""Test validate_ports function."""

from xrpl_controller.core import validate_ports_or_ids


def test_validate_ports():
    """Test validate_ports function."""
    assert validate_ports_or_ids(10, 11) is None
    assert validate_ports_or_ids(0, 1) is None

    try:
        validate_ports_or_ids(-1, 100)
        raise AssertionError()
    except ValueError:
        pass

    try:
        validate_ports_or_ids(0, -1)
        raise AssertionError()
    except ValueError:
        pass

    try:
        validate_ports_or_ids(60000, 60000)
        raise AssertionError()
    except ValueError:
        pass
