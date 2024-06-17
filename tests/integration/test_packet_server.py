"""Integration tests for the packet server."""

# import multiprocessing
# import time
#
# import grpc
#
# from protos import packet_pb2, packet_pb2_grpc
# from tests.dummy_strategy import DummyStrategy
# from xrpl_controller.packet_server import serve
#
#
# # TODO: Make sure this test will get coverage.
# #  It currently does cover the method but since the serve() method does not terminate, it will not get coverage.
# def run_server():
#     """Run the packet server with a dummy strategy."""
#     strategy = DummyStrategy(False, False, False)
#     serve(strategy)
#
#
# def test_serve_integration():
#     """Test the server by sending a packet to it."""
#     # Start the server in a separate process to prevent blocking
#     server_process = multiprocessing.Process(target=run_server)
#     server_process.start()
#
#     time.sleep(5)
#
#     # Create a client to send requests to the server
#     channel = grpc.insecure_channel("localhost:50051")
#     stub = packet_pb2_grpc.PacketServiceStub(channel)
#
#     packet = packet_pb2.Packet(data=b"test", from_port=10, to_port=20)
#     response = stub.send_packet(packet)
#     assert response.data == b"test"
#     assert response.action == 0
#
#     server_process.terminate()
#     server_process.join()
