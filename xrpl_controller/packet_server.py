"""This module is responsible for receiving the incoming packets from the interceptor and returning a response."""

from concurrent import futures

import grpc
from protos import packet_pb2, packet_pb2_grpc
from xrpl_controller import controller


class PacketService(packet_pb2_grpc.PacketServiceServicer):
    """This class is responsible for receiving the incoming packets from the interceptor and returning a response."""

    def SendPacket(self, request, context):
        """
        This function receives the packet from the interceptor and passes it to the controller.

        Args:
            request: intercepted sslstream
            context: grpc context

        Returns: acknowledgement message (This needs to be changed to a more meaningful response)

        """
        controller.handle_packet(request.data)
        return packet_pb2.PacketAck(action=1, data=request.data, port=request.port)


def serve():
    """
    This function starts the server and listens for incoming packets.

    Returns: None

    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    packet_pb2_grpc.add_PacketServiceServicer_to_server(PacketService(), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
