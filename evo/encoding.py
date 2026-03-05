from pathlib import Path
import numpy as np
from deap import tools
import sys
import random

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rocket_controller.strategies.utils import BYZZ_MUTATE_METHODS
from protos import packet_pb2, ripple_pb2


class BaseEncoding:
    def __init__(self):
        pass

    @staticmethod
    def mate(ind1, ind2):
        return ind1, ind2

    @staticmethod
    def mutate(ind, **kwargs):
        return (ind,)

    def repair(self):
        # 将mate和mutate之后的基因修复为合理的类型
        raise NotImplementedError("repair method not implemented")

    def to_dict(self):
        raise NotImplementedError("to_json method not implemented")

    @staticmethod
    def sample(configs):
        raise NotImplementedError("sample method not implemented")


class EvoDelayByzzPartitionStrategyEncoding(BaseEncoding):
    def __init__(
        self,
        partition,
        delay_rules,
        byzz_rules,
        partition_seq,
        partition_duration,
        num_nodes,
        delay_min,
        delay_max,
        byzz_min_seq,
        byzz_max_seq,
    ):
        self.partition = partition
        self.delay_rules = delay_rules
        self.byzz_rules = byzz_rules

        self.partition_seq = partition_seq
        self.partition_duration = partition_duration
        self.num_nodes = num_nodes
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.byzz_min_seq = byzz_min_seq
        self.byzz_max_seq = byzz_max_seq

        self._message_types = {
            30: ripple_pb2.TMTransaction,
            31: ripple_pb2.TMGetLedger,
            32: ripple_pb2.TMLedgerData,
            33: ripple_pb2.TMProposeSet,
            34: ripple_pb2.TMStatusChange,
            35: ripple_pb2.TMHaveTransactionSet,
            41: ripple_pb2.TMValidation,
        }

        # 随机初始化delay和byzz的rules
        self.delay_rules = set()
        self.byzz_rules = set()

    def add_random_delay_rules(self, to_add=5):
        # (seq, from_node, to_node, message_type, delay)

        choices = [
            (seq, from_node, to_node, message_type)
            for seq in range(self.byzz_min_seq, self.byzz_max_seq + 1)
            for from_node in range(self.num_nodes)
            for to_node in range(self.num_nodes)
            if from_node != to_node
            for message_type in self._message_types.values()
        ]
        if len(choices) < to_add:
            # 全部加进去，随机赋值delay
            for choice in choices:
                delay = random.randint(self.delay_min, self.delay_max)
                self.delay_rules.add((*choice, delay))
        else:
            selected = random.sample(choices, to_add)
            for choice in selected:
                delay = random.randint(self.delay_min, self.delay_max)
                self.delay_rules.add((*choice, delay))

    def add_random_byzz_rules(self, to_add=5):
        # (seq, to_node, message_type, method)
        # 但是这里每个message_type只能选一个方法
        # 只使用在BYZZ_MUTATE_METHODS中支持的message types
        supported_message_types = [
            msg_type
            for msg_type in self._message_types.values()
            if msg_type in BYZZ_MUTATE_METHODS
        ]
        choices = [
            (seq, to_node, message_type)
            for seq in range(self.byzz_min_seq, self.byzz_max_seq + 1)
            for to_node in range(self.num_nodes)
            for message_type in supported_message_types
        ]
        if len(choices) < to_add:
            for c in choices:
                method = random.choice(BYZZ_MUTATE_METHODS[c[2]])
                self.byzz_rules.add((*c, method))
        else:
            selected = random.sample(choices, to_add)
            for c in selected:
                method = random.choice(BYZZ_MUTATE_METHODS[c[2]])
                self.byzz_rules.add((*c, method))

    def to_dict(self):
        delay_rules_list = [
            [d[0], d[1], d[2], d[3].__name__, d[4]] for d in self.delay_rules
        ]
        byzz_rules_list = [[b[0], b[1], b[2].__name__, b[3]] for b in self.byzz_rules]
        return {
            "partition": self.partition,
            "delay_rules": delay_rules_list,
            "byzz_rules": byzz_rules_list,
            "partition_seq": self.partition_seq,
            "partition_duration": self.partition_duration,
        }

    def sample(configs):
        ind = EvoDelayByzzPartitionStrategyEncoding(
            partition=[random.randint(0, 1) for _ in range(configs["number_of_nodes"])],
            delay_rules=set(),
            byzz_rules=set(),
            partition_seq=configs["partition_seq"],
            partition_duration=configs["partition_duration"],
            num_nodes=configs["number_of_nodes"],
            delay_min=configs["min_delay_ms"],
            delay_max=configs["max_delay_ms"],
            byzz_min_seq=configs["byzz_min_seq"],
            byzz_max_seq=configs["byzz_max_seq"],
        )
        ind.add_random_delay_rules(to_add=5)
        ind.add_random_byzz_rules(to_add=5)
        return ind

    def repair(self): ...

    @staticmethod
    def _crossover_rules(rules1, rules2):
        """
        基于集合的规则交叉
        从两个父代的规则集合中随机分割并组合，生成两个子代
        """
        rules_list_1 = list(rules1)
        rules_list_2 = list(rules2)

        # 随机分割第一个父代的规则
        split_idx_1 = random.randint(0, len(rules_list_1)) if rules_list_1 else 0
        child1 = set(rules_list_1[:split_idx_1]) | set(rules_list_2[split_idx_1:])

        # 随机分割第二个父代的规则
        split_idx_2 = random.randint(0, len(rules_list_2)) if rules_list_2 else 0
        child2 = set(rules_list_2[:split_idx_2]) | set(rules_list_1[split_idx_2:])

        return child1, child2

    @staticmethod
    def mate(ind1, ind2):
        """
        交叉操作：对三个成分分别进行交叉
        - partition: 基于社区结构的交叉（保留共识分配）
        - delay_rules: 基于集合的交叉
        - byzz_rules: 基于集合的交叉
        """
        # 1. partition 交叉 - 基于社区结构的交叉
        # 如果两个父代对某个节点的分配相同，保持该分配；否则随机选择
        new_partition_1 = []
        new_partition_2 = []

        for i in range(len(ind1.partition)):
            if ind1.partition[i] == ind2.partition[i]:
                # 两个父代的分配相同，保持一致
                new_partition_1.append(ind1.partition[i])
                new_partition_2.append(ind2.partition[i])
            else:
                # 两个父代的分配不同，随机选择
                if random.random() < 0.5:
                    new_partition_1.append(ind1.partition[i])
                    new_partition_2.append(ind2.partition[i])
                else:
                    new_partition_1.append(ind2.partition[i])
                    new_partition_2.append(ind1.partition[i])

        ind1.partition = new_partition_1
        ind2.partition = new_partition_2

        # 2. delay_rules 交叉
        if ind1.delay_rules or ind2.delay_rules:
            ind1.delay_rules, ind2.delay_rules = ind1._crossover_rules(
                ind1.delay_rules, ind2.delay_rules
            )

        # 3. byzz_rules 交叉
        if ind1.byzz_rules or ind2.byzz_rules:
            ind1.byzz_rules, ind2.byzz_rules = ind1._crossover_rules(
                ind1.byzz_rules, ind2.byzz_rules
            )

        return ind1, ind2

    @staticmethod
    def mutate(ind):
        """
        变异操作：对三个成分分别独立进行变异（各50%概率）
        确保至少有一个地方被变异
        """
        mutated = False

        # 1. partition 变异 - 50% 概率翻转一个节点
        if random.random() < 0.5:
            flip_idx = random.randint(0, len(ind.partition) - 1)
            ind.partition[flip_idx] = 1 - ind.partition[flip_idx]
            mutated = True

        # 2. delay_rules 变异 - 50% 概率修改或添加/删除规则
        if random.random() < 0.5:
            op = random.choice(["modify", "add", "delete"])

            if op == "modify" and ind.delay_rules:
                # 修改一个规则的 delay 值
                rule_to_modify = random.choice(list(ind.delay_rules))
                ind.delay_rules.discard(rule_to_modify)
                new_delay = random.randint(ind.delay_min, ind.delay_max)
                ind.delay_rules.add(rule_to_modify[:-1] + (new_delay,))
            elif op == "add":
                # 添加一个新规则
                ind.add_random_delay_rules(to_add=1)
            elif op == "delete" and ind.delay_rules:
                # 删除一个规则
                ind.delay_rules.discard(random.choice(list(ind.delay_rules)))

            mutated = True

        # 3. byzz_rules 变异 - 50% 概率修改方法或添加/删除规则
        if random.random() < 0.5:
            op = random.choice(["modify", "add", "delete"])

            if op == "modify" and ind.byzz_rules:
                # 修改一个规则的 mutation method
                rule_to_modify = random.choice(list(ind.byzz_rules))
                ind.byzz_rules.discard(rule_to_modify)
                new_method = random.choice(BYZZ_MUTATE_METHODS[rule_to_modify[2]])
                ind.byzz_rules.add(rule_to_modify[:-1] + (new_method,))
            elif op == "add":
                # 添加一个新规则
                ind.add_random_byzz_rules(to_add=1)
            elif op == "delete" and ind.byzz_rules:
                # 删除一个规则
                ind.byzz_rules.discard(random.choice(list(ind.byzz_rules)))

            mutated = True

        # 确保至少有一个地方被变异
        if not mutated:
            which = random.choice(["partition", "delay_rules", "byzz_rules"])
            if which == "partition":
                idx = random.randint(0, len(ind.partition) - 1)
                ind.partition[idx] = 1 - ind.partition[idx]
            elif which == "delay_rules":
                ind.add_random_delay_rules(to_add=1)
            else:
                ind.add_random_byzz_rules(to_add=1)

        return (ind,)


class RandomDelayByzzStrategyEncoding(BaseEncoding):
    def __init__(self):
        pass

    def repair(self):
        pass

    def to_dict(self):
        return {}

    @staticmethod
    def sample(configs):
        return RandomDelayByzzStrategyEncoding()


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
        return {
            "partition_seq": self.partition_seq,
            "partition_duration": self.partition_duration,
        }


class RandomByzzStrategyEncoding(BaseEncoding):
    def __init__(self):
        pass

    def to_dict(self):
        return {}

    def sample(configs):
        return RandomByzzStrategyEncoding()


class RandomDelayStrategyEncoding(BaseEncoding):
    def __init__(self):
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
        self.encoding_len = (
            num_nodes * (num_nodes - 1) * num_message_types * self.num_seqs
        )
        self.encoding = []

    @staticmethod
    def sample(configs):
        num_nodes, delay_min, delay_max, byzz_min_seq, byzz_max_seq = (
            configs["number_of_nodes"],
            configs["min_delay_ms"],
            configs["max_delay_ms"],
            configs["byzz_min_seq"],
            configs["byzz_max_seq"],
        )
        num_message_types = 7
        ind = EvoDelayBySeqStrategyEncoding(
            byzz_min_seq,
            byzz_max_seq,
            num_nodes,
            delay_min,
            delay_max,
            num_message_types,
        )
        ind.encoding = [
            np.random.randint(delay_min, delay_max) for _ in range(ind.encoding_len)
        ]
        return ind

    def to_dict(self):
        return {"delays": self.encoding}


if __name__ == "__main__":
    strategy = "EvoDelayByzzPartitionStrategy"

    encoding = strategy + "Encoding"
    Enc = getattr(sys.modules[__name__], encoding)

    print(Enc.__name__)

    configs = {
        "partition_seq": 5,
        "partition_duration": 3000,
        "number_of_nodes": 7,
        "min_delay_ms": 0,
        "max_delay_ms": 1000,
        "byzz_min_seq": 5,
        "byzz_max_seq": 10,
    }

    ind = Enc.sample(configs)
    print("=== Original Individual ===")
    print(ind.to_dict())
    import yaml

    encoding = yaml.dump({"encoding": ind.to_dict()})
    print(encoding)

    # ========== 调试 mate 操作 ==========
    print("\n\n=== Testing mate() operation ===")

    # 创建两个个体用于交叉
    ind1 = Enc.sample(configs)
    ind2 = Enc.sample(configs)

    print("\n--- Parent 1 ---")
    parent1_dict = ind1.to_dict()
    print(f"partition: {parent1_dict['partition']}")
    print(f"delay_rules count: {len(parent1_dict['delay_rules'])}")
    print(f"byzz_rules count: {len(parent1_dict['byzz_rules'])}")

    print("\n--- Parent 2 ---")
    parent2_dict = ind2.to_dict()
    print(f"partition: {parent2_dict['partition']}")
    print(f"delay_rules count: {len(parent2_dict['delay_rules'])}")
    print(f"byzz_rules count: {len(parent2_dict['byzz_rules'])}")

    # 执行交叉
    child1, child2 = Enc.mate(ind1, ind2)

    print("\n--- Child 1 (after mate) ---")
    child1_dict = child1.to_dict()
    print(f"partition: {child1_dict['partition']}")
    print(f"delay_rules count: {len(child1_dict['delay_rules'])}")
    print(f"byzz_rules count: {len(child1_dict['byzz_rules'])}")

    print("\n--- Child 2 (after mate) ---")
    child2_dict = child2.to_dict()
    print(f"partition: {child2_dict['partition']}")
    print(f"delay_rules count: {len(child2_dict['delay_rules'])}")
    print(f"byzz_rules count: {len(child2_dict['byzz_rules'])}")

    print("\n--- Verification ---")
    print(
        f"Child 1 partition is different from both parents: {child1_dict['partition'] != parent1_dict['partition'] or child1_dict['partition'] != parent2_dict['partition']}"
    )
    print(
        f"Child 2 partition is different from both parents: {child2_dict['partition'] != parent1_dict['partition'] or child2_dict['partition'] != parent2_dict['partition']}"
    )
    print(
        f"Child 1 delay_rules count is between 0 and sum: {0 <= len(child1_dict['delay_rules']) <= len(parent1_dict['delay_rules']) + len(parent2_dict['delay_rules'])}"
    )
    print(
        f"Child 2 delay_rules count is between 0 and sum: {0 <= len(child2_dict['delay_rules']) <= len(parent1_dict['delay_rules']) + len(parent2_dict['delay_rules'])}"
    )
    print(
        f"Child 1 byzz_rules count is between 0 and sum: {0 <= len(child1_dict['byzz_rules']) <= len(parent1_dict['byzz_rules']) + len(parent2_dict['byzz_rules'])}"
    )
    print(
        f"Child 2 byzz_rules count is between 0 and sum: {0 <= len(child2_dict['byzz_rules']) <= len(parent1_dict['byzz_rules']) + len(parent2_dict['byzz_rules'])}"
    )
    
    # ========== 调试 mutate 操作 ==========
    print("\n\n=== Testing mutate() operation ===")
    
    # 创建一个个体用于变异
    test_ind = Enc.sample(configs)
    
    print("\n--- Original Individual ---")
    original_dict = test_ind.to_dict()
    print(f"partition: {original_dict['partition']}")
    print(f"delay_rules count: {len(original_dict['delay_rules'])}")
    print(f"byzz_rules count: {len(original_dict['byzz_rules'])}")
    
    # 执行变异多次，观察不同的变异结果
    print("\n--- After mutate (10 times) ---")
    for i in range(10):
        mutated_ind = Enc.sample(configs)
        original_before = mutated_ind.to_dict()
        
        mutated_ind, = Enc.mutate(mutated_ind)
        mutated_after = mutated_ind.to_dict()
        
        partition_changed = original_before['partition'] != mutated_after['partition']
        delay_changed = len(original_before['delay_rules']) != len(mutated_after['delay_rules'])
        byzz_changed = len(original_before['byzz_rules']) != len(mutated_after['byzz_rules'])
        
        print(f"Iteration {i+1}: partition_changed={partition_changed}, delay_changed={delay_changed}, byzz_changed={byzz_changed}")
    
    print("\n--- Example: Before and After Single Mutate ---")
    example_ind = Enc.sample(configs)
    example_before = example_ind.to_dict()
    
    example_ind, = Enc.mutate(example_ind)
    example_after = example_ind.to_dict()
    
    print(f"Partition before: {example_before['partition']}")
    print(f"Partition after:  {example_after['partition']}")
    print(f"Delay rules before count: {len(example_before['delay_rules'])}")
    print(f"Delay rules after count:  {len(example_after['delay_rules'])}")
    print(f"Byzz rules before count: {len(example_before['byzz_rules'])}")
    print(f"Byzz rules after count:  {len(example_after['byzz_rules'])}")
