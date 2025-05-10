"""This file contains a class to run and manage evolutionary based testing approaches."""
import argparse
import random

from rocket_controller.cli_helper import process_args, str_to_strategy
from rocket_controller.packet_server import serve
from rocket_controller.strategies import Strategy


class EvoTestManager:
    """Manager for evolutionary based testing approaches."""

    def __init__(self, evo_type='delay', n=3):
        """
        Initializes an EvoTestManager.
        
        Args:
            evo_type: type of approach ⋹ {'delay', 'priority'}.
            n: number of nodes
        """
        self.n = n
        if not evo_type in ['delay', 'priority']:
            raise ValueError(f"evo_type should be in {{'delay', 'priority'}}, but got {evo_type}")

        self.evo_type = evo_type
        self.strategy = "EvoDelayStrategy" if self.evo_type == 'delay' else "EvoPriorityStrategy"

    def run(self, encoding: list[int]):
        """
        Run rocket with set configurations.

        Args:
            encoding: encoding of numbers to be used by evolutionary strategy
        """

        if len(encoding) != (required_length := (self.n * (self.n - 1)) * 7):
            raise ValueError(f"Encoding should be of length {required_length}, but got {len(encoding)}")

        params_dict = process_args(
            argparse.Namespace(strategy=self.strategy,   # Not yet implemented!
                               nodes=self.n,
                               partition=None,           # No partition
                               nodes_unl=None,           # Default nodes_unl
                               network_config=None,      # Default network_config
                               config=None,              # Default config
                               overrides={'encoding': encoding})
        )

        # Do note: for more granular configurations, modify params_dict directly
        # See the constructor of Strategy for all possible parameters
        # The above Namespace may even be removed entirely as its functionalities are limited
        strategy: Strategy = str_to_strategy(self.strategy)(**params_dict)
        server = serve(strategy)
        server.wait_for_termination()


if __name__ == "__main__":
    manager = EvoTestManager('delay', 3) # TODO config here?
    manager.run([random.randint(0, 4000) for _ in range(42)])
