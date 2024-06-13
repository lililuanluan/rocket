"""Tests for timestamp_microseconds method in core.py."""
from datetime import datetime

from xrpl_controller.core import timestamp_ms


def test_timestamp_ms():
    # Checking whether timestamp is actually correct w.r.t. epoch is not testable for us.
    # We rely on the correctness of Python itself.
    time = datetime(2024, 1, 2, 3, 4, 5, 6)
    assert timestamp_ms(time) == 1704161045000
