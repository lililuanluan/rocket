"""This file contains a class to run and manage byzzfuzz based testing approaches."""
import csv
import glob
import shutil
from datetime import datetime
import random
import subprocess
import sys
from pathlib import Path
from time import sleep

import yaml
from typing import Tuple

from rocket_controller.helper import format_datetime

def process_results(log_dir):
    result_files = glob.glob(f"logs/{log_dir}/**/result-*.csv")
    validation_times = []

    for result_file in result_files:
        with open(result_file, 'r') as f:
            csv_reader = csv.DictReader(f)
            for row in csv_reader:
                if row['ledger_seq'] != '2':
                    validation_times.append(float(row['time_to_validation']))
    return sum(validation_times) / len(validation_times) if validation_times else 0

class ByzzFuzzTestManager:
    """Manager for byzzfuzz based testing approaches."""

    def __init__(self, config_path='byzzfuzz_test_manager.yaml'): 
        """
        Initializes ByzzFuzzTestManager.
        
        Args:
            config_path: path to the config file.
        """
        config_path = Path(config_path)
        if not config_path.exists():
            raise ValueError(f"config file {config_path} does not exist")
        with open(config_path, 'r') as f:
            self._config = yaml.safe_load(f)

        # general section of the config file
        strategy = self._config['general']['strategy']
        if not strategy in ['ByzzFuzzBaseline', 'ByzzFuzzStrategy']:
            raise ValueError(f"strategy should be in {{'ByzzFuzzBaseline', 'ByzzFuzzStrategy'}}, but got {strategy}")
        self.strategy = strategy

        self.seed = self._config['general'].get('seed', None)
        if self.seed is None:
            self.seed = random.randint(0, 1000000)
            print(f"Seed not specified, using {self.seed}")
        random.seed(self.seed)

        # strategy section of the config file
        if self.strategy == "ByzzFuzzStrategy":
            byzzfuzz = self._config['byzzfuzz']
            self.rounds = byzzfuzz['rounds']
            self.min_network_faults = byzzfuzz['min_network_faults']
            self.max_network_faults = byzzfuzz['max_network_faults']
            self.min_process_faults = byzzfuzz['min_process_faults']
            self.max_process_faults = byzzfuzz['max_process_faults']
            self.small_scope = byzzfuzz['small_scope']
        elif self.strategy == "ByzzFuzzBaseline":
            baseline = self._config['baseline']
            self.drop_probability = baseline['drop_probability']
            self.corrupt_probability = baseline['corrupt_probability']

    def run_rocket(self, log_dir: str, network_faults: int = 0, process_faults: int = 0, retry: int = 0):
        """
        Run rocket with set configurations.

        Args:
            retry: Number of retries left.
            log_dir: Directory where logs should be stored.
        """
        Path.mkdir(Path(f"logs/{log_dir}"), parents=True, exist_ok=True)
        with open(f"logs/{log_dir}/run_info.txt", mode="a") as f:
            f.write(f"Seed: {self.seed}")
        
        debug_file_path = Path(f"logs/{log_dir}/debug_messages.txt")
        if self.strategy == "ByzzFuzzStrategy":
            command = f"{sys.executable} -u -m rocket_controller --rounds {self.rounds} --network_faults {network_faults} --process_faults {process_faults} --small_scope {self.small_scope} --log_dir {log_dir} ByzzFuzzStrategy > {debug_file_path} 2>&1"
        elif self.strategy == "ByzzFuzzBaseline":
            command = f"{sys.executable} -u -m rocket_controller --drop_probability {self.drop_probability} --corrupt_probability {self.corrupt_probability} --log_dir {log_dir} ByzzFuzzBaseline > {debug_file_path} 2>&1"

        process = subprocess.Popen(command, shell=True)
        return_code = process.wait()
        if return_code != 0: # TODO return_code does probably not work, but will be different anyway when DinD is used.
            if retry < 3:
                retry += 1
                print(f"Rocket failed on attempt {retry}. Retrying...")
                shutil.copytree(f"logs/{log_dir}", f"logs/failed/{log_dir}/retry-{retry}")
                shutil.rmtree(f"logs/{log_dir}")
                sleep(5)
                return self.run_rocket(encoding, log_dir, retry)
            raise Exception(f"Rocket failed after {retry} retries. THIS IS NOT GOOD!")

        average_validation_time = process_results(log_dir)
        with open(f"logs/{log_dir}/run_info.txt", mode="a") as f:
            f.write(f"\nAverage validation time: {average_validation_time} seconds")
        print(f"Average validation time: {average_validation_time} seconds")

    def main(self):
        if self.strategy == "ByzzFuzzStrategy":
            for network_faults in range(self.min_network_faults, self.max_network_faults + 1):
                for process_faults in range(self.min_process_faults, self.max_process_faults + 1):
                    print(f"Testing combination: network_faults={network_faults}, process_faults={process_faults}")
                    start_time = datetime.now()
                    log_dir = f"{format_datetime(start_time)}/network_faults-{network_faults}_process_faults-{process_faults}"
                    self.run_rocket(log_dir, network_faults, process_faults)
        elif self.strategy == "ByzzFuzzBaseline":
            start_time = datetime.now()
            log_dir = f"{format_datetime(start_time)}/drop-{self.drop_probability}_corrupt-{self.corrupt_probability}"
            self.run_rocket(log_dir)
        return

if __name__ == "__main__":
    manager = ByzzFuzzTestManager()
    manager.main()