"""Core module."""

from datetime import datetime

# The delay value which indicated a drop. This is the max value of an u32 datatype in Rust.
MAX_U32 = 2**32 - 1


def flatten(xss: list[list[int]]) -> list[int]:
    """
    Flatten a 2D list.

    Args:
        xss: A 2D integer list to be flattened.

    Returns:
        list[int]: A flattened list.
    """
    return [x for xs in xss for x in xs]


def format_datetime(time: datetime) -> str:
    """
    Format a datetime to a fixed format.

    Args:
        time: Timestamp

    Returns:
        str: Formatted time
    """
    return time.strftime("%Y_%m_%d_%Hh%Mm")
