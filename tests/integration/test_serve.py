"""Integration tests for the packet server."""

from unittest.mock import Mock, patch

import grpc

from protos import packet_pb2, packet_pb2_grpc
from tests.default_test_variables import configs
from tests.integration.dummy_strategy import DummyStrategy
from xrpl_controller.packet_server import serve


@patch(
    "tests.integration.dummy_strategy.Strategy.init_configs",
    return_value=configs,
)
def run_server(mock_configs):
    """Run the packet server with a dummy strategy."""
    strategy = DummyStrategy()
    mock_configs.assert_called_once()
    mock_iteration_type = Mock()
    strategy.iteration_type = mock_iteration_type
    strategy.network.port_to_id_dict = {10: 0, 20: 1}
    server = serve(strategy)
    mock_iteration_type.set_server.assert_called_once()
    mock_iteration_type.add_iteration.assert_called_once()
    return server


def test_serve_integration():
    """Test the server by sending a packet to it."""
    server = run_server()

    # Create a client to send requests to the server
    channel = grpc.insecure_channel("localhost:50051")
    stub = packet_pb2_grpc.PacketServiceStub(channel)
    packet = packet_pb2.Packet(data=b"testtest", from_port=10, to_port=20)
    response = stub.send_packet(packet)
    assert response.data == b"testtest"
    assert response.action == 0

    server.stop(grace=1)
