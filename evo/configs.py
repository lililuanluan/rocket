import yaml
from datetime import datetime


class EvotestConfig:
    def __init__(self, cur_dir, rocket_dir, interceptor_dir, logs_dir, tmp_dir):
        self.cur_dir = cur_dir
        self.rocket_dir = rocket_dir
        self.interceptor_dir = interceptor_dir
        self.logs_dir = logs_dir
        self.tmp_dir = tmp_dir
        self._start_datetime = datetime.now().strftime("%Y_%m_%d_%Hh%Mm_%Ss")
        with open(self.cur_dir / "network.yaml", "r") as f:
            self.base_network_config = yaml.safe_load(f)
            self.number_of_nodes = self.base_network_config["number_of_nodes"]
            self.byzz_nodes = self.base_network_config["byzz_nodes"]

        with open(self.cur_dir / "evotest.yaml", "r") as f:
            self.config = yaml.safe_load(f)
            self.delay_min = self.config["encoding"]["min_value"]
            self.delay_max = self.config["encoding"]["max_value"]
            self.ripple_image = self.config["ripple-image"]
            self.seed = self.config.get("seed", 42)
            self.max_parallel_workers = self.config.get("max_parallel_workers", 1)
            self.fitness_function = self.config.get(
                "fitness_function", "mean_validation_time"
            )
            self.max_ledger_seq = self.config.get("max_ledger_seq", 15)
            self.population_size = self.config.get("population_size", 10)
            self.mu = self.config.get("mu", 4)
            self.max_generation = self.config.get("max_generation", 10)
            
        
        self.test_log_dir_identifier = self._start_datetime
        self.test_log_dir = self.logs_dir / self.test_log_dir_identifier



    @staticmethod
    def from_dirs(dirs):
        return EvotestConfig(
            cur_dir=dirs["cur_dir"],
            rocket_dir=dirs["rocket_dir"],
            interceptor_dir=dirs["interceptor_dir"],
            logs_dir=dirs["logs_dir"],
            tmp_dir=dirs["tmp_dir"],
        )
