"""Helper module with useful shared functions."""

from datetime import datetime
from typing import Any

import yaml

# The delay value which indicates a drop. This is the max value of an u32 datatype in Rust.
MAX_U32 = 2**32 - 1


def flatten(xss: list[list[int]]) -> list[int]:
    """
    Flatten a 2D integer list.

    Args:
        xss: A 2D integer list to be flattened.

    Returns:
        list[int]: A flattened integer list.
    """
    return [x for xs in xss for x in xs]


def validate_ports_or_ids(num_1: int, num_2: int):
    """
    Validate whether 2 ports or ID's are not equal to each other.

    Args:
        num_1: Port or ID 1.
        num_2: Port or ID 2.

    Raises:
        ValueError: If the ports or ID's are equal or if any of the ports or ID's are negative.
    """
    if num_1 < 0 or num_2 < 0:
        raise ValueError("Received ports or ID's must be non-negative.")

    elif num_1 == num_2:
        raise ValueError(
            f"Received ports or ID's can not be equal to each other, value: {num_1}."
        )


def format_datetime(time: datetime) -> str:
    """
    Format a datetime to a fixed format.

    Args:
        time: Timestamp.

    Returns:
        str: Formatted timestamp.
    """
    return time.strftime("%Y_%m_%d_%Hh%Mm")


# This method is not allowed to have a return type, tox will complain and will fail the pipeline.
# This method is solely used to suppress tox warnings.
def parse_to_list_of_ints(lst: list[list[int]] | list[int]):
    """
    Parses a list[list[int]] | list[int] type to a list[int] type.

    Args:
        lst: The list to be parsed.

    Returns:
        Parsed list.

    Raises:
        ValueError: If lst is not a list[int].
    """
    # Case when var is indeed a 1D list of integers
    if isinstance(lst, list) and all(isinstance(i, int) for i in lst):
        return lst

    raise ValueError("Given argument is not a 1D integer list.")


# This method is not allowed to have a return type, tox will complain and will fail the pipeline.
# This method is solely used to suppress tox warnings.
def parse_to_2d_list_of_ints(lst: list[list[int]] | list[int]):
    """
    Parses a list[list[int]] | list[int] type to a list[list[int]] type.

    Args:
        lst: The list to be parsed.

    Returns:
        Parsed list.

    Raises:
        ValueError: If lst is not a list[list[int]].
    """
    if isinstance(lst, list) and all(
        isinstance(sublist, list) and all(isinstance(item, int) for item in sublist)
        for sublist in lst
    ):
        return lst

    raise ValueError("Given argument is not a 2D integer list.")


def format_filename(filename: str, filetype: str) -> str:
    """
    Format a filename, ensuring it ends with a certain filetype extension.

    Args:
        filename: Filename.
        filetype: File extension.

    Returns:
        Formatted filename.
    """
    filetype = "." + filetype if not filetype.startswith(".") else filetype
    return filename + filetype if not filename.endswith(filetype) else filename


def yaml_to_dict(filepath: str) -> dict[str, Any]:
    """
    Read a yaml file into a dictionary.

    Args:
        filepath: Path of the yaml file.

    Returns:
        A dictionary containing all fields in the yaml file.
    """
    path = format_filename(filepath, "yaml")

    with open(path, "rb") as f:
        result: dict[str, Any] = yaml.safe_load(f)
        result = result if result is not None else {}

    return result
