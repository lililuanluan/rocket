"""Tests for list parser functions in core.py."""

import pytest

from xrpl_controller.core import parse_to_2d_list_of_ints, parse_to_list_of_ints


def test_parsers():
    """Test the imported parser functions."""
    lst_1d: list[int] | list[list[int]] = [1, 2, 3]
    lst_2d: list[int] | list[list[int]] = [[1, 2, 3], [4, 5, 6]]

    parse_to_list_of_ints(lst_1d)  # Should not raise exception
    parse_to_2d_list_of_ints(lst_2d)  # Should not raise exception

    with pytest.raises(ValueError):
        parse_to_list_of_ints(lst_2d)  # Should raise exception

    with pytest.raises(ValueError):
        parse_to_2d_list_of_ints(lst_1d)  # Should raise exception
