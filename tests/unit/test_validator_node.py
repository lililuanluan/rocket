"""Tests for ValidatorNode class."""

from tests.default_test_variables import node_0


def test_constructor():
    """Test the constructor."""
    assert node_0.peer.port == 10
    assert node_0.ws_public.host == "test-ws-pub"
    assert node_0.ws_public.port == 20
    assert node_0.rpc.host == "test-rpc"
    assert node_0.validator_key_data.validation_private_key == "K3YZER"


def test_to_string():
    """Test the __str__ method of ValidatorNode."""
    assert node_0.__str__() == (
        "ValidatorNode(peer=SocketAddress(host=test_peer, port=10), "
        "ws_public=SocketAddress(host=test-ws-pub, port=20), "
        "ws_private=SocketAddress(host=test-ws-adm, port=30), "
        "rpc=SocketAddress(host=test-rpc, port=40), "
        "validator_key_data=ValidatorKeyData(status=status0, validation_key=keyZER, "
        "validation_private_key=K3YZER, validation_public_key=PUBZER, validation_seed=T3STZER))"
    )
