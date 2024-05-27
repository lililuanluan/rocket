"""Core module."""

# The delay value which indicated a drop. This is the max value of an u32 datatype in Rust.
MAX_U32 = 2**32 - 1


def add(x: int, y: int) -> int:
    """
    Add two numbers.

    Args:
        x: First number.
        y: Second number.

    Returns: Result of addition.
    """
    return x + y


def print_hi(name: str) -> None:
    """
    Print hi {user}.

    Args:
        name: User's name.
    """
    print(f"Hi, {name}")


def flatten(xss: list[list[int]]) -> list:
    """
    Flatten a 2D list.

    Args:
        xss: A 2D integer list to be flattened.

    Returns:
    A flattened list.
    """
    return [x for xs in xss for x in xs]
