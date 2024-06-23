"""Tests for MessageActionStack."""

import pytest

from xrpl_controller.message_action import MessageAction
from xrpl_controller.message_action_buffer import MessageActionBuffer


def test_init():
    """Test __init__ method."""
    with pytest.raises(ValueError):
        stack = MessageActionBuffer(0)

    stack = MessageActionBuffer(1)
    assert stack.capacity == 1
    assert stack.messages == []


def test_add():
    """Test add method."""
    stack = MessageActionBuffer(2)
    msg1 = MessageAction(b"1", b"m1", 10)
    stack.add(msg1)
    assert stack.messages == [msg1]

    msg2 = MessageAction(b"2", b"m2", 11)
    stack.add(msg2)
    assert stack.messages == [msg1, msg2]

    msg3 = MessageAction(b"3", b"m3", 13)
    stack.add(msg3)
    assert stack.messages == [msg2, msg3]


def test_check_message():
    """Test check_previous_messages method."""
    stack = MessageActionBuffer(2)
    msg1 = MessageAction(b"1", b"m1", 10)
    stack.add(msg1)
    msg2 = MessageAction(b"2", b"m2", 11)
    stack.add(msg2)

    assert stack.match_previous_messages(b"2") == (True, (b"m2", 11))

    assert stack.match_previous_messages(b"3") == (False, (b"3", 0))
