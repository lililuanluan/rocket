"""Tests for `add` function."""

from xrpl_controller import core


def test_add():
    """
    Test adding two integers.

    :return:
    """
    assert core.add(1, 2) == 3
