"""This file contains a class to run and manage evolutionary based testing approaches."""
import argparse
import random
import subprocess
import sys
from pathlib import Path

import yaml
from typing import Tuple

from mypy.stubinfo import stub_distribution_name

from rocket_controller.cli_helper import process_args, str_to_strategy
from rocket_controller.packet_server import serve
from rocket_controller.strategies import Strategy


class EvoTestManager:
    """Manager for evolutionary based testing approaches."""

    def __init__(self, config_path='evo_test_manager.yaml'):
        """
        Initializes an EvoTestManager.
        
        Args:
            config_path: path to the config file.
        """
        config_path = Path(config_path)
        if not config_path.exists():
            raise ValueError(f"config file {config_path} does not exist")
        with open(config_path, 'r') as f:
            self._config = yaml.safe_load(f)

        # General section of the config file
        nodes = self._config['general']['nodes']
        if nodes < 2:
            raise ValueError(f"nodes should be at least 2, but got {nodes}")
        self.nodes = nodes


        strategy = self._config['general']['strategy']
        if not strategy in ['EvoDelayStrategy', 'EvoPriorityStrategy']:
            raise ValueError(f"strategy should be in {{'EvoDelayStrategy', 'EvoPriorityStrategy'}}, but got {strategy}")
        self.strategy = strategy

        seed = self._config['general'].get('seed', None)
        if seed is None:
            seed = random.randint(0, 1000000)
            print(f"seed not specified, using {seed}")
        random.seed(seed)

        # Evolution section of the config file
        population_size = self._config['evolution']['population_size']
        if population_size < 2:
            raise ValueError(f"population_size should be at least 2, but got {population_size}")
        self.population_size = population_size

        generations = self._config['evolution']['generations']
        if generations < 1:
            raise ValueError(f"generations should be at least 1, but got {generations}")
        self.generations = generations

        # Encoding section of the config file
        encoding = self._config['encoding']
        self.encoding_min = encoding['min_value']
        self.encoding_max = encoding['max_value']
        self.encoding_length = (self.nodes * (self.nodes - 1)) * 7


    def initial_population(self):
        return [random.randint(self.encoding_min, self.encoding_max) for _ in range(self.encoding_length)]

    def selection(self, results: list[Tuple[list[int], list[int]]]):
        # TODO first list[int] is a placeholder, should be the type of results from run_rocket
        # TODO run fitness function on the results, then determine which ones are fit
        # Temporarily passthrough all populations
        populations = []
        for result, population in results:
            populations.append(population)
        return populations

    def reproduction(self, populations: list[list[int]]):
        # TODO Crossover

        # TODO Mutation

        # Temporarily passthrough all populations
        for i in range(len(populations)):
            populations[i] = self.initial_population()
        return populations


    def run_rocket(self, encoding: list[int]):
        """
        Run rocket with set configurations.

        Args:
            encoding: encoding of numbers to be used by evolutionary strategy
        """

        if len(encoding) != self.encoding_length:
            raise ValueError(f"Encoding should be of length {self.encoding_length}, but got {len(encoding)}")
        #
        # params_dict = process_args(
        #     argparse.Namespace(strategy=self.strategy,   # Not yet implemented!
        #                        nodes=self.nodes,
        #                        partition=None,           # No partition
        #                        nodes_unl=None,           # Default nodes_unl
        #                        network_config=None,      # Default network_config
        #                        config=None,              # Default config
        #                        overrides={'encoding': encoding})
        # )
        # Do note: for more granular configurations, modify params_dict directly
        # See the constructor of Strategy for all possible parameters
        # The above Namespace may even be removed entirely as its functionalities are limited
        print(f"Running rocket with encoding {encoding}")

        command = [sys.executable, "-m", "rocket_controller", "--nodes", str(self.nodes), "--encoding", str(encoding), self.strategy]

        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            stdout, stderr = process.communicate()
            return_code = process.wait()
            if return_code != 0:
                print(f"Rocket failed: {stderr}")
                return [], encoding
            return [], encoding
        except Exception as e:
            print(f"Rocket failed: {e}")
            return [], encoding

    def run_evolution_round(self, populations: list[list[int]]):
        results = []
        print(f"Running evolution with {len(populations)} populations.")
        for population in populations:
            # This is the part that could be run in parallel, if we figure out how with docker networking and stuff.
            results.append(self.run_rocket(population))
        return results

    def main(self):
        populations = [self.initial_population() for _ in range(self.population_size)]
        for _ in range(self.generations):
            print(f"Generation {_+1}")
            results = self.run_evolution_round(populations)
            selected = self.selection(results)
            populations = self.reproduction(selected)
        return


if __name__ == "__main__":
    manager = EvoTestManager()
    manager.main()
