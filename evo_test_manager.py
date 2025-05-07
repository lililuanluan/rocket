import argparse

from rocket_controller.cli_helper import process_args, str_to_strategy
from rocket_controller.packet_server import serve
from rocket_controller.strategies import Strategy


class EvoTestManager:

    def run(self, encoding):
        params_dict = process_args(
            argparse.Namespace(strategy="EvoPriorityStrategy",
                               nodes=3,
                               partition=None,
                               nodes_unl=None,
                               network_config=None,
                               config=None,
                               overrides={'encoding': encoding})
        )
        strategy: Strategy = str_to_strategy('RandomFuzzer')(**params_dict)
        server = serve(strategy)
        server.wait_for_termination()


if __name__ == "__main__":
    EvoTestManager.run([])
