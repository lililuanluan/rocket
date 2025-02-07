"""Tests for `flatten` function."""

from rocket_controller.helper import flatten


def test_flatten_1():
    """Test whether flatten function works. Multiple lists in the bigger list."""
    lst = [[1], [2, 3], [1]]
    assert flatten(lst) == [1, 2, 3, 1]


def test_flatten_2():
    """Test whether flatten function works. Multiple lists in the bigger list with multiple numbers in each list."""
    lst = [[1, 2, 3, 1, 9, 2], [2, 3], [1, 4, 1]]
    assert flatten(lst) == [1, 2, 3, 1, 9, 2, 2, 3, 1, 4, 1]


def test_flatten_3():
    """Test whether flatten function works. No numbers."""
    lst = []
    assert flatten(lst) == []


def test_flatten_4():
    """Test whether flatten function works. No numbers, nested list."""
    lst = [[]]
    assert flatten(lst) == []


def test_flatten_5():
    """Test whether flatten function works. All numbers in one list."""
    lst = [[1, 2, 3, 4]]
    assert flatten(lst) == [1, 2, 3, 4]


def test_flatten_6():
    """Test whether flatten function works. One number."""
    lst = [[1]]
    assert flatten(lst) == [1]
