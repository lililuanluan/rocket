import argparse
import random

from rocket_controller.cli_helper import process_args, str_to_strategy
from rocket_controller.packet_server import serve
from rocket_controller.strategies import Strategy


class EvoTestManager:

    @staticmethod
    def run(encoding):
        params_dict = process_args(
            argparse.Namespace(strategy="EvoDelayStrategy",
                               nodes=3,
                               partition=None,
                               nodes_unl=None,
                               network_config=None,
                               config=None,
                               overrides={'encoding': encoding})
        )
        strategy: Strategy = str_to_strategy('EvoDelayStrategy')(**params_dict)
        server = serve(strategy)
        server.wait_for_termination()


if __name__ == "__main__":
    EvoTestManager.run([random.randint(0, 4000) for _ in range(42)])
