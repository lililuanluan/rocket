"""Tests for ValidatorNode class."""

from xrpl_controller.validator_node_info import (
    ValidatorNode,
    ValidatorKeyData,
    SocketAddress,
)

node = ValidatorNode(
    SocketAddress("test_peer", 10),
    SocketAddress("test-ws-pub", 20),
    SocketAddress("test-ws-adm", 30),
    SocketAddress("test-rpc", 40),
    ValidatorKeyData("status", "key", "K3Y", "PUB", "T3ST"),
)


def test_constructor():
    """Test the constructor."""
    assert node.peer.port == 10
    assert node.ws_public.host == "test-ws-pub"
    assert node.ws_public.port == 20
    assert node.rpc.host == "test-rpc"
    assert node.validator_key_data.validation_private_key == "K3Y"


def test_to_string():
    """Test the __str__ method of ValidatorNode."""
    assert node.__str__() == (
        "ValidatorNode(peer=SocketAddress(host=test_peer, port=10), "
        "ws_public=SocketAddress(host=test-ws-pub, port=20), "
        "ws_private=SocketAddress(host=test-ws-adm, port=30), "
        "rpc=SocketAddress(host=test-rpc, port=40), "
        "validator_key_data=ValidatorKeyData(status=status, validation_key=key, "
        "validation_private_key=K3Y, validation_public_key=PUB, validation_seed=T3ST))"
    )
