"""Tests for format_filename method in core.py."""

from xrpl_controller.core import format_filename


def test_format_filename():
    """Test format_filename function."""
    filename = "test"
    filename2 = "test.tzt"

    assert format_filename(filename, "tst") == "test.tst"
    assert format_filename(filename, ".tst") == "test.tst"
    assert format_filename(filename2, "tzt") == "test.tzt"
    assert format_filename(filename2, ".tzt") == "test.tzt"
    assert format_filename(None, ".tst") is None
    assert format_filename(None, "TEST..test") is None
