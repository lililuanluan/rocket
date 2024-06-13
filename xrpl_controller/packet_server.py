"""This module is responsible for receiving the incoming packets from the interceptor and returning a response."""

import datetime
from concurrent import futures
from typing import List

import grpc
import tomllib

from protos import packet_pb2, packet_pb2_grpc
from xrpl_controller.core import format_datetime, validate_ports
from xrpl_controller.csv_logger import ActionLogger
from xrpl_controller.strategies.strategy import Strategy
from xrpl_controller.validator_node_info import (
    SocketAddress,
    ValidatorKeyData,
    ValidatorNode,
)

HOST = "localhost"


class PacketService(packet_pb2_grpc.PacketServiceServicer):
    """This class is responsible for receiving the incoming packets from the interceptor and returning a response."""

    def __init__(self, strategy: Strategy):
        """
        Constructor for the PacketService class.

        Args:
            strategy: the strategy to use while serving packets
        """
        self.strategy = strategy
        self.logger: ActionLogger | None = None

    def send_packet(self, request, context):
        """
        This function receives the packet from the interceptor and passes it to the controller.

        Every action taken by the defined strategy will be logged in ../execution_logs.

        Args:
            request: packet containing intercepted data
            context: grpc context

        Returns:
            the possibly modified packet and an action

        Raises:
            ValueError: if request.from_port == request.to_port or if any is negative
        """
        timestamp = int(datetime.datetime.now().timestamp() * 1000)
        validate_ports(request.from_port, request.to_port)

        (data, action) = self.strategy.process_packet(request)

        if self.strategy.keep_action_log:
            if not self.logger:
                raise RuntimeError("Logger was not initialized")
            self.logger.log_action(
                action=action,
                from_port=request.from_port,
                to_port=request.to_port,
                data=data,
                custom_timestamp=timestamp,
            )

        return packet_pb2.PacketAck(data=data, action=action)

    def send_validator_node_info(
        self, request_iterator, context
    ) -> packet_pb2.ValidatorNodeInfoAck:
        """
        This function receives the validator node info from the interceptor and passes it to the controller.

        Args:
            request_iterator: Iterator of validator node info.
            context: grpc context.

        Returns:
            ValidatorNodeInfoAck: An acknowledgement.
        """
        validator_node_list: List[ValidatorNode] = []
        for request in request_iterator:
            validator_node_list.append(
                ValidatorNode(
                    peer=SocketAddress(
                        host=HOST,
                        port=request.peer_port,
                    ),
                    ws_public=SocketAddress(
                        host=HOST,
                        port=request.ws_public_port,
                    ),
                    ws_admin=SocketAddress(
                        host=HOST,
                        port=request.ws_admin_port,
                    ),
                    rpc=SocketAddress(
                        host=HOST,
                        port=request.rpc_port,
                    ),
                    validator_key_data=ValidatorKeyData(
                        status=request.status,
                        validation_key=request.validation_key,
                        validation_private_key=request.validation_private_key,
                        validation_public_key=request.validation_public_key,
                        validation_seed=request.validation_seed,
                    ),
                )
            )
        self.strategy.update_network(validator_node_list)

        if self.strategy.keep_action_log:
            if (
                self.logger is not None
            ):  # Close the previous logger if there was a previous one
                self.logger.close()
            self.logger = ActionLogger(
                format_datetime(datetime.datetime.now()), validator_node_list
            )

        return packet_pb2.ValidatorNodeInfoAck(status="Received validator node info")

    def get_config(self, request, context):
        """
        This function sends the config specified in `network-config.toml`, to the interceptor.

        Args:
            request: The request containing the Config.
            context: gRPC context.

        Returns:
            Config: The Config object.
        """
        with open("network-config.toml", "rb") as f:
            config = tomllib.load(f)

        partition_list: List[List[int]] = config.get("network_partition")
        partitions = map(lambda x: packet_pb2.Partition(nodes=x), partition_list)

        return packet_pb2.Config(
            base_port_peer=config.get("base_port_peer"),
            base_port_ws=config.get("base_port_ws"),
            base_port_ws_admin=config.get("base_port_ws_admin"),
            base_port_rpc=config.get("base_port_rpc"),
            number_of_nodes=config.get("number_of_nodes"),
            partitions=partitions,
        )


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


def serve_for_automated_tests(strategy: Strategy) -> grpc.Server:
    """
    This function starts the server and listens for incoming packets.

    Returns: None

    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    packet_pb2_grpc.add_PacketServiceServicer_to_server(PacketService(strategy), server)
    server.add_insecure_port("[::]:50051")
    server.start()
    return server
