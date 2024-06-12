"""Tests for format_datetime method."""

import datetime

from xrpl_controller.core import format_datetime


def test_format():
    """Test format_datetime."""
    timestamp = datetime.datetime(2024, 1, 2, 3, 4, 5, 6)
    assert format_datetime(timestamp) == "2024_01_02_03h04m"
