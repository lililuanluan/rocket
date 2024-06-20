"""Tests for the PacketServer class."""

from unittest.mock import Mock, patch

import pytest

from protos import packet_pb2
from xrpl_controller.packet_server import PacketService
from xrpl_controller.strategies.encoder_decoder import PacketEncoderDecoder


def test_send_packet_no_log():
    """Test the send_packet method of PacketService without logging."""
    packet = packet_pb2.Packet(data=b"test", from_port=10, to_port=20)
    mock_strategy = Mock()
    mock_strategy.process_packet.return_value = (packet.data, 0)
    mock_strategy.keep_action_log = False
    packet_server = PacketService(mock_strategy)
    packet_ack = packet_server.send_packet(packet, None)
    assert packet_ack.data == b"test"
    assert packet_ack.action == 0
    mock_strategy.process_packet.assert_called_once()


def test_send_packet_with_log_no_logger():
    """Test the send_packet method of PacketService with logging but no existing logger."""
    packet = packet_pb2.Packet(data=b"test", from_port=10, to_port=20)
    mock_strategy = Mock()
    mock_strategy.process_packet.return_value = (packet.data, 0)
    mock_strategy.keep_action_log = True
    packet_server = PacketService(mock_strategy)
    with pytest.raises(RuntimeError):
        packet_server.send_packet(packet, None)
        mock_strategy.process_packet.assert_called_once()


def test_send_packet_with_log_and_logger():
    """Test the send_packet method of PacketService with logging and an existing logger."""
    packet = packet_pb2.Packet(data=b"test", from_port=10, to_port=20)
    mock_strategy = Mock()
    mock_strategy.process_packet.return_value = (packet.data, 0)
    mock_strategy.keep_action_log = True
    packet_server = PacketService(mock_strategy)
    packet_server.logger = Mock()
    with patch.object(
        PacketEncoderDecoder, "decode_packet", return_value=(Mock(), 61)
    ) as mock_decode_packet:
        packet_ack = packet_server.send_packet(packet, None)
    assert mock_decode_packet.call_count == 2
    assert packet_ack.data == b"test"
    assert packet_ack.action == 0
    packet_server.logger.log_action.assert_called_once()
    mock_strategy.process_packet.assert_called_once()


def test_send_validator_node_info_no_log():
    """Test the send_validator_node_info method of PacketService without logging."""
    mock_strategy = Mock()
    mock_strategy.keep_action_log = False
    packet_server = PacketService(mock_strategy)
    request_iterator = [packet_pb2.ValidatorNodeInfo()]
    response = packet_server.send_validator_node_info(request_iterator, None)
    assert response.status == "Received validator node info"


def test_send_validator_node_info_with_log():
    """Test the send_validator_node_info method of PacketService with logging without existing logger."""
    mock_strategy = Mock()
    mock_strategy.keep_action_log = True
    packet_server = PacketService(mock_strategy)
    request_iterator = [packet_pb2.ValidatorNodeInfo()]
    mock_logger = Mock()
    with patch("xrpl_controller.packet_server.ActionLogger", return_value=mock_logger):
        response = packet_server.send_validator_node_info(request_iterator, None)
        assert response.status == "Received validator node info"
        assert packet_server.logger is not None


def test_send_validator_node_info_with_existing_logger():
    """Test the send_validator_node_info method of PacketService with an existing logger."""
    mock_strategy = Mock()
    mock_strategy.keep_action_log = True
    packet_server = PacketService(mock_strategy)
    mock_logger = Mock()
    with patch("xrpl_controller.packet_server.ActionLogger", return_value=mock_logger):
        packet_server.logger = mock_logger
        request_iterator = [packet_pb2.ValidatorNodeInfo()]
        response = packet_server.send_validator_node_info(request_iterator, None)
        assert response.status == "Received validator node info"
        mock_logger.close.assert_called_once()


def test_get_config():
    """Test the get_config method of PacketService."""
    # TODO: Maybe add assertion on ports so this test fails. This test initializes a config with default values so
    #  all ports set to zero which is guaranteed to fail in the interceptor.
    mock_strategy = Mock()
    mock_strategy.network.network_config = {
        "base_port_peer": 0,
        "base_port_ws": 0,
        "base_port_ws_admin": 0,
        "base_port_rpc": 0,
        "number_of_nodes": 0,
        "network_partition": [[]],
    }
    packet_server = PacketService(mock_strategy)
    request = packet_pb2.Config()
    response = packet_server.get_config(request, None)
    assert response.base_port_peer == mock_strategy.network.network_config.get("base_port_peer")
    assert response.base_port_ws == mock_strategy.network.network_config.get("base_port_ws")
    assert response.base_port_ws_admin == mock_strategy.network.network_config.get(
        "base_port_ws_admin"
    )
    assert response.base_port_rpc == mock_strategy.network.network_config.get("base_port_rpc")
    assert response.number_of_nodes == mock_strategy.network.network_config.get(
        "number_of_nodes"
    )
    assert list(response.partitions) == list(
        map(
            lambda x: packet_pb2.Partition(nodes=x),
            mock_strategy.network.network_config.get("network_partition"),
        )
    )
