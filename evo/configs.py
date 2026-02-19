import yaml

class EvotestConfig:
    def __init__(self, cur_dir, rocket_dir, interceptor_dir, logs_dir, tmp_dir):
        self.cur_dir = cur_dir
        self.rocket_dir = rocket_dir
        self.interceptor_dir = interceptor_dir
        self.logs_dir = logs_dir
        self.tmp_dir = tmp_dir
        with open(self.cur_dir / "network.yaml", "r") as f:
            network_config = yaml.safe_load(f)
            self.number_of_nodes = network_config["number_of_nodes"]
        
        
        with open(self.cur_dir / "evotest.yaml", "r") as f:
            self.config = yaml.safe_load(f)

    @staticmethod
    def from_dirs(dirs):
        return EvotestConfig(
            cur_dir=dirs["cur_dir"],
            rocket_dir=dirs["rocket_dir"],
            interceptor_dir=dirs["interceptor_dir"],
            logs_dir=dirs["logs_dir"],
            tmp_dir=dirs["tmp_dir"],
        )
    
