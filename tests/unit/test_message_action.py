"""Tests for MessageAction class."""

from rocket_controller.message_action import MessageAction


def test_init():
    """Test __init__ method."""
    msg = MessageAction()
    assert msg.initial_message == b""
    assert msg.final_message == b""
    assert msg.action == -1


def test_builder_initials_msg():
    """Test set_initial_message method."""
    msg = MessageAction().set_initial_message(b"test")
    assert msg.initial_message == b"test"


def test_builder_final_msg():
    """Test set_final_message method."""
    msg = MessageAction().set_final_message(b"test2")
    assert msg.final_message == b"test2"


def test_builder_action():
    """Test set_action method."""
    msg = MessageAction().set_action(10)
    assert msg.action == 10
