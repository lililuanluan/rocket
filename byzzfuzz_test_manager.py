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
    result_files = glob.glob(f"{log_dir}/**/result-*.csv")
    validation_times = []

    for result_file in result_files:
        with open(result_file, 'r') as f:
            csv_reader = csv.DictReader(f)
            for row in csv_reader:
                if row['ledger_seq'] != '2':
                    validation_times.append(float(row['time_to_validation']))
    return sum(validation_times) / len(validation_times) if validation_times else 0

def cleanup_docker(hostname_prefix: str):
    try:
        client = docker.from_env()

        all_containers = client.containers.list(all=True)
        containers = [c for c in all_containers if c.name.startswith(hostname_prefix)]
        for container in containers:
            try:
                container.stop()
                container.remove()
            except Exception as e:
                print(f"Failed to stop container {container.name}. Error: {e}")
    except Exception as e:
        print(f"Error cleaning up docker containers: {e}")

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
        
        self.image = "rocket-image-aiste"
        self.xrpl_image = "xrpllabsofficial/xrpld:2.4.0"
        # self.output_path = "/data/home/bwassenaar/shared_rocket"
        self.main_hostname_prefix = "AM_Baseline"
        self.shared_volume = f"{self.main_hostname_prefix}_data"
        self.workers = 5  # workers refers to the amount of rocket controllers started at the same time. This means you will need 10 free threads per worker.
        # Do not use more than 5 on the research server!

    def run_rocket(self, network_faults: int, process_faults: int, testcase: int, retry: int = 0):
        """
        Run rocket with set configurations.

        Args:
            retry: Number of retries left.
            log_dir: Directory where logs should be stored.
        """
        if self.strategy == "ByzzFuzzStrategy":
            print(f"Running rocket with process faults: {process_faults}, network faults: {network_faults}")
            hostname_prefix = f"{self.main_hostname_prefix}_T{testcase}_P{process_faults}_N{network_faults}_R{retry}"
        elif self.strategy == "ByzzFuzzBaseline":
            print(f"Running rocket with corrupt probability: {self.corrupt_probability}, drop probability: {self.drop_probability}")
            hostname_prefix = f"{self.main_hostname_prefix}_T{testcase}_P{self.corrupt_probability}_N{self.drop_probability}_R{retry}"

        log_dir = f"/shared/logs/{self.main_hostname_prefix}/{hostname_prefix}"
        Path.mkdir(Path(log_dir), parents=True, exist_ok=True)
        with open(f"{log_dir}/run_info.txt", mode="a") as f:
            f.write(f"Seed: {self.seed}")
            if self.strategy == "ByzzFuzzStrategy":
                f.write(f"\nStrategy: {self.strategy}, Rounds: {self.rounds}, Network Faults: {network_faults}, Process Faults: {process_faults}, Small Scope: {self.small_scope}")
            elif self.strategy == "ByzzFuzzBaseline":
                f.write(f"\nStrategy: {self.strategy}, Drop Probability: {self.drop_probability}, Corrupt Probability: {self.corrupt_probability}")

        name = f"{hostname_prefix}_controller"

        if self.strategy == "ByzzFuzzStrategy":
            python_args = ["-m", "rocket_controller", self.strategy, "--rounds", str(self.rounds), "--network_faults",
                str(network_faults), "--process_faults", str(process_faults), "--small_scope", str(self.small_scope), "--hostname_prefix", hostname_prefix, "--log_dir", log_dir]
        elif self.strategy == "ByzzFuzzBaseline":
            python_args = ["-m", "rocket_controller", self.strategy, "--drop_probability", str(self.drop_probability), "--corrupt_probability",
                str(self.corrupt_probability), "--hostname_prefix", hostname_prefix, "--log_dir", log_dir]

        client = docker.from_env()
        try:
            container = client.containers.run(
                image=self.image,
                name=name,
                command=python_args,
                network="rocket_net",
                auto_remove=False,
                environment={
                    "ROCKET_NETWORK_MOUNT": self.shared_volume,
                    "ROCKET_XRPLD_DOCKER_CONTAINER": self.xrpl_image
                },
                volumes={
                    "/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "rw"},
                    self.shared_volume: {"bind": "/shared", "mode": "rw"},
                },
                detach=True,
            )

            with open(f"{log_dir}/stdout.txt", mode="w") as out_file:
                result = container.wait(timeout=30*60)
                logs = container.logs(stdout=True, stderr=True, timestamps=True)
                out_file.write(logs.decode(errors="ignore"))
            exit_code = result.get("StatusCode", -1)
        except Exception as e:
            if retry < 2:
                retry += 1
                print(f"Rocket failed on attempt {retry}. Retrying...")
                cleanup_docker(hostname_prefix)
                sleep(5)
                return self.run_rocket(network_faults, process_faults, testcase, retry)
            raise Exception(f"Rocket timed out after {retry} retries. THIS IS NOT GOOD!")

        if exit_code != 0:
            if retry < 2:
                retry += 1
                print(f"Rocket failed on attempt {retry}. Retrying...")
                cleanup_docker(hostname_prefix)
                sleep(5)
                return self.run_rocket(network_faults, process_faults, testcase, retry)
            raise Exception(f"Rocket failed after {retry} retries. THIS IS NOT GOOD!")

        average_validation_time = process_results(log_dir)
        with open(f"{log_dir}/run_info.txt", mode="a") as f:
            f.write(f"\nAverage validation time: {average_validation_time} seconds")
        print(f"Average validation time: {average_validation_time} seconds")
        cleanup_docker(hostname_prefix)
    
    def run_configuration(self, network_faults: int, process_faults: int):
        results = []
        print(f"Running tests for one configuration...")

        with ThreadPoolExecutor(max_workers=self.workers) as executor:
            for testcase in range(5):
                executor.submit(self.run_rocket, network_faults, process_faults, testcase, 0)

    def main(self):
        start_time = datetime.now()
        shutil.copytree("./rocket_interceptor/network", f"/shared/network")

        if self.strategy == "ByzzFuzzStrategy":
            for network_faults in range(self.min_network_faults, self.max_network_faults + 1):
                for process_faults in range(self.min_process_faults, self.max_process_faults + 1):
                    print(f"Testing combination: network_faults={network_faults}, process_faults={process_faults}")
                    #log_dir = f"{format_datetime(start_time)}/network_faults-{network_faults}_process_faults-{process_faults}"
                    self.run_configuration(network_faults, process_faults)
        elif self.strategy == "ByzzFuzzBaseline":
            print(f"Testing baseline with drop_probability={self.drop_probability}, corrupt_probability={self.corrupt_probability}")
            #log_dir = f"{format_datetime(start_time)}/drop-{self.drop_probability}_corrupt-{self.corrupt_probability}"
            self.run_configuration(network_faults, process_faults)
        return

if __name__ == "__main__":
    manager = ByzzFuzzTestManager()
    manager.main()