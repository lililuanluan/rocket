"""This module is responsible for receiving the incoming packets from the interceptor and returning a response."""

from concurrent import futures

import csv
from datetime import datetime
import grpc
import os
from protos import packet_pb2, packet_pb2_grpc
from xrpl_controller.strategy import Strategy

MAX_U32 = 2**32 - 1


class PacketService(packet_pb2_grpc.PacketServiceServicer):
    """This class is responsible for receiving the incoming packets from the interceptor and returning a response."""

    def __init__(self, strategy: Strategy):
        """
        Constructor for the PacketService class.

        Args:
            strategy: the strategy to use while serving packets
        """
        self.strategy = strategy
        file_path = "../execution_logs/execution_log.csv"
        csv_file = open(file_path, mode="w", newline="")
        self.writer = csv.writer(csv_file)
        self.writer.writerow(["timestamp", "action", "from_port", "to_port", "data"])

    def SendPacket(self, request, context):
        """
        This function receives the packet from the interceptor and passes it to the controller.

        Args:
            request: intercepted sslstream
            context: grpc context

        Returns: the possibly modified packet and an action
            action 0: send immediately without delay
            action MAX: drop the packet
            action 0<x<MAX: delay the packet x ms

        """
        (data, action) = self.strategy.handle_packet(request.data)

        self.writer.writerow(
            [
                datetime.now(),
                "Send"
                if action == 0
                else "Drop"
                if action == MAX_U32
                else "Delay:" + str(action) + "ms",
                request.from_port,
                request.to_port,
                data.hex(),
            ]
        )

        return packet_pb2.PacketAck(data=data, action=action)


def serve(strategy: Strategy):
    """
    This function starts the server and listens for incoming packets.

    Returns: None

    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    packet_pb2_grpc.add_PacketServiceServicer_to_server(PacketService(strategy), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    server.wait_for_termination()
