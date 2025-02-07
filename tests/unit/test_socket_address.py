"""Tests for SocketAddress class."""

from rocket_controller.validator_node_info import SocketAddress


def test_constructor():
    """Test the constructor."""
    socket_addr = SocketAddress("TEST", 0)
    assert socket_addr.host == "TEST"
    assert socket_addr.port == 0


def test_as_url():
    """Test the as_url() method."""
    socket_addr = SocketAddress("TEST2", 3000)
    assert socket_addr.as_url() == "TEST2:3000"


def test_to_string():
    """Test the __str__ method."""
    socket_addr = SocketAddress("TEST", 42)
    assert socket_addr.__str__() == "SocketAddress(host=TEST, port=42)"
