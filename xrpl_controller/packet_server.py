"""This module is responsible for receiving the incoming packets from the interceptor and returning a response."""

from concurrent import futures
from typing import List

import grpc
import tomllib

from protos import packet_pb2, packet_pb2_grpc
from xrpl_controller.core import MAX_U32, validate_ports
from xrpl_controller.csv_logger import ActionLogger
from xrpl_controller.request_ledger_data import store_validator_node_info
from xrpl_controller.strategies.strategy import Strategy
from xrpl_controller.validator_node_info import (
    SocketAddress,
    ValidatorKeyData,
    ValidatorNode,
)

HOST = "localhost"


class PacketService(packet_pb2_grpc.PacketServiceServicer):
    """This class is responsible for receiving the incoming packets from the interceptor and returning a response."""

    def __init__(self, strategy: Strategy, keep_log: bool = True):
        """
        Constructor for the PacketService class.

        Args:
            strategy: the strategy to use while serving packets
            keep_log: whether to keep track of a log containing all actions taken
        """
        self.strategy = strategy
        self.keep_log = keep_log
        if keep_log:
            self.logger = None

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
        validate_ports(request.from_port, request.to_port)

        if (
            self.strategy.auto_parse_identical
            and self.strategy.check_previous_message(
                request.from_port, request.to_port, request.data
            )[0]
        ):
            (data, action) = self.strategy.check_previous_message(
                request.from_port, request.to_port, request.data
            )[1]

        else:
            if not self.strategy.check_communication(
                request.from_port, request.to_port
            ):
                (data, action) = (request.data, MAX_U32)
            else:
                (data, action) = self.strategy.handle_packet(request.data)

            self.strategy.set_message_action(
                request.from_port, request.to_port, request.data, data, action
            )

        if self.keep_log:
            self.logger.log_action(
                action=action,
                from_port=request.from_port,
                to_port=request.to_port,
                data=data,
            )

        return packet_pb2.PacketAck(data=data, action=action)

    def send_validator_node_info(self, request_iterator, context):
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
        store_validator_node_info(validator_node_list)
        self.strategy.update_network(validator_node_list)

        if self.keep_log:
            if (
                self.logger is not None
            ):  # Close the previous logger if there was a previous one
                self.logger.close()
            self.logger = ActionLogger(validator_node_list)

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

        return packet_pb2.Config(
            base_port_peer=config.get("base_port_peer"),
            base_port_ws=config.get("base_port_ws"),
            base_port_ws_admin=config.get("base_port_ws_admin"),
            base_port_rpc=config.get("base_port_rpc"),
            number_of_nodes=config.get("number_of_nodes"),
        )


def serve(strategy: Strategy, keep_log: bool = True):
    """
    This function starts the server and listens for incoming packets.

    Returns: None

    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    packet_pb2_grpc.add_PacketServiceServicer_to_server(
        PacketService(strategy, keep_log), server
    )
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
