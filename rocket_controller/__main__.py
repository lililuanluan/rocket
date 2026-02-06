"""Entry point of the application, run with python -m rocket_controller."""

import argparse

from rocket_controller.cli_helper import parse_args, process_args, str_to_strategy
from rocket_controller.packet_server import serve
from rocket_controller.strategies import Strategy


def main(args: argparse.Namespace) -> None:
    """
    Main entry point.

    Args:
        args: Command line arguments.
    """
    params_dict = process_args(args)

    grpc_port = params_dict.get("grpc_port", 50051)

    strategy: Strategy = str_to_strategy(args.strategy)(**params_dict)
    server = serve(strategy, grpc_port=grpc_port)
    server.wait_for_termination()


if __name__ == "__main__":  # pragma: no cover
    parsed_args = parse_args()
    main(parsed_args)
