class BaseEncoding:
    def __init__(self):
        pass

    def mate(self, other, **kwargs):
        pass

    def mutate(self, **kwargs):
        pass
    
    def repair(self):
        # 将mate和mutate之后的基因修复为合理的类型
        pass

class RandomDelayEncoding(BaseEncoding):
    def __init__(self, num_nodes, delay_min, delay_max):
        self.num_nodes = num_nodes
        self.delay_min = delay_min
        self.delay_max = delay_max

def get_encoding_from_strategy_config(strategy: str):
    mapping = {
        "RandomDelayStrategy": RandomDelayEncoding,
    }
    return mapping.get(strategy)