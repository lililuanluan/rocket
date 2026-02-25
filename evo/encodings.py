import numpy as np
from deap import tools
import sys


class BaseEncoding:
    def __init__(self):
        pass

    @staticmethod
    def mate(ind1, ind2):
        raise NotImplementedError("mate method not implemented")

    def mutate(self, **kwargs):
        raise NotImplementedError("mutate method not implemented")

    def repair(self):
        # 将mate和mutate之后的基因修复为合理的类型
        raise NotImplementedError("repair method not implemented")

    def to_dict(self):
        raise NotImplementedError("to_json method not implemented")

    @staticmethod
    def sample(configs):
        raise NotImplementedError("sample method not implemented")


class RandomDelayByzzStrategyEncoding(BaseEncoding):
    def __init__(self):
        pass

    def mate(self, ind1, ind2):
        pass

    def mutate(self, ind):
        pass

    def repair(self):
        pass

    def to_dict(self):
        return {}

    def sample(configs):
        return RandomDelayByzzStrategyEncoding()



class EvoDelayByzzPartition(BaseEncoding):
    pass

class RandomDelayByzzPartitionStrategyEncoding(BaseEncoding):
    # 配置：partition seq，partition duration，做成一个列表 [(seq1, duration1), (seq2, duration2), ...]，
    def __init__(
        self,
        partition_seq,
        partition_duration,
    ):
        self.partition_seq = partition_seq
        self.partition_duration = partition_duration

    @staticmethod
    def sample(configs):
        partition_seq, partition_duration = (
            configs["partition_seq"],
            configs["partition_duration"],
        )
        ind = RandomDelayByzzPartitionStrategyEncoding(
            partition_seq=partition_seq,
            partition_duration=partition_duration,
        )

        return ind

    def repair(self):
        pass

    def to_dict(self):
        return {}

    def sample(configs):
        return RandomByzzStrategyEncoding()


class RandomDelayStrategyEncoding(BaseEncoding):
    def __init__(self):
        pass

    def mate(self, ind1, ind2):
        pass

    def mutate(self, ind):
        pass

    def repair(self):
        pass

    def to_dict(self):
        return {}

    def sample(configs):
        return RandomDelayStrategyEncoding()


class EvoDelayStrategyEncoding(BaseEncoding):
    def __init__(self, num_nodes, delay_min, delay_max, num_message_types=7):
        self.num_nodes = num_nodes
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.num_message_types = num_message_types
        self.encoding_len = num_nodes * (num_nodes - 1) * num_message_types
        self.encoding = []

    @staticmethod
    def sample(configs):
        num_nodes, delay_min, delay_max = (
            configs["number_of_nodes"],
            configs.get("min_delay_ms"),
            configs.get("max_delay_ms"),
        )
        num_message_types = 7
        ind = EvoDelayStrategyEncoding(
            num_nodes, delay_min, delay_max, num_message_types
        )
        ind.encoding = [
            np.random.randint(delay_min, delay_max) for _ in range(ind.encoding_len)
        ]
        return ind

    def repair(self):
        self.encoding = [
            int(round(max(self.delay_min, min(self.delay_max, x))))
            for x in self.encoding
        ]

    @staticmethod
    def mate(ind1, ind2):
        tools.cxSimulatedBinaryBounded(
            ind1.encoding, ind2.encoding, eta=3.0, low=ind1.delay_min, up=ind1.delay_max
        )
        ind1.repair()
        ind2.repair()
        return ind1, ind2

    @staticmethod
    def mutate(ind):
        tools.mutGaussian(
            ind.encoding,
            mu=0,
            sigma=(ind.delay_max - ind.delay_min) / 100.0,
            indpb=1.0 / ind.encoding_len,
        )
        ind.repair()
        return (ind,)

    def to_dict(self):
        return {"delays": self.encoding}


class EvoDelayBySeqStrategyEncoding(EvoDelayStrategyEncoding):
    def __init__(
        self,
        byzz_min_seq,
        byzz_max_seq,
        num_nodes,
        delay_min,
        delay_max,
        num_message_types=7,
    ):
        # 左右都包含
        self.byzz_min_seq = byzz_min_seq
        self.byzz_max_seq = byzz_max_seq
        self.num_nodes = num_nodes
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.num_message_types = num_message_types
        self.num_seqs = byzz_max_seq - byzz_min_seq + 1
        self.encoding_len = num_nodes * (num_nodes - 1) * num_message_types * self.num_seqs
        self.encoding = []

    @staticmethod
    def sample(configs):
        num_nodes, delay_min, delay_max, byzz_min_seq, byzz_max_seq = (
            configs["number_of_nodes"],
            configs.get("min_delay_ms"),
            configs.get("max_delay_ms"),
            configs.get("byzz_min_seq"),
            configs.get("byzz_max_seq"),
        )
        num_message_types = 7
        ind = EvoDelayBySeqStrategyEncoding(
            byzz_min_seq, byzz_max_seq, num_nodes, delay_min, delay_max, num_message_types
        )
        ind.encoding = [
            np.random.randint(delay_min, delay_max) for _ in range(ind.encoding_len)
        ]
        return ind

    def to_dict(self):
        return {"delays": self.encoding}


if __name__ == "__main__":
    strategy = "RandomDelayStrategy"

    encoding = strategy + "Encoding"
    print(getattr(sys.modules[__name__], encoding))
