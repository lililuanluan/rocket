from pathlib import Path
import copy
import numpy as np
from deap import tools
import sys
import random
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rocket_controller.strategies.utils import BYZZ_MUTATE_METHODS
from protos import packet_pb2, ripple_pb2

MESSAGE_TYPE_MAP = {
    30: ripple_pb2.TMTransaction,
    31: ripple_pb2.TMGetLedger,
    32: ripple_pb2.TMLedgerData,
    33: ripple_pb2.TMProposeSet,
    34: ripple_pb2.TMStatusChange,
    35: ripple_pb2.TMHaveTransactionSet,
    41: ripple_pb2.TMValidation,
}


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
        # raise NotImplementedError("repair method not implemented")
        ...

    def to_dict(self):
        raise NotImplementedError("to_dict method not implemented")

    @staticmethod
    def sample(configs):
        raise NotImplementedError("sample method not implemented")


# ------------------------------------------------------ 重构 ----------------------------------------------------


class ByzzEncoding:
    byzz_modes = [
        "none",  # no byzantine behavior
        "random",  # random byzantine behavior
        "sparse_rules",  # a set of rules: (seq, to_node, message_type) -> mutation method
    ]
    _message_types = MESSAGE_TYPE_MAP

    def __init__(
        self, mode, num_nodes, byzz_nodes, byzz_min_seq, byzz_max_seq, init_num_rules=5
    ):
        if mode not in self.byzz_modes:
            raise ValueError(f"Invalid byzz mode: {mode}")
        self.mode = mode
        self.num_nodes = num_nodes
        self.byzz_nodes = byzz_nodes or []
        self.byzz_min_seq = byzz_min_seq
        self.byzz_max_seq = byzz_max_seq
        self.byzz_rules = None  # list of (seq, to_node, message_type, mutation_method)
        self.init_num_rules = init_num_rules
        self._sample_byzz_rules()

    def _random_byzz_method(self, message_type, exclude=None, include_noop=False):
        methods = BYZZ_MUTATE_METHODS[message_type]
        if not include_noop:
            methods = [m for m in methods if m != "do_nothing"]
        if exclude is not None and len(methods) > 1:
            methods = [m for m in methods if m != exclude]
        return random.choice(methods)

    def add_random_byzz_rules(self, to_add=1):
        if self.mode != "sparse_rules":
            return
        if self.byzz_rules is None:
            self.byzz_rules = set()

        supported_message_types = [
            msg_type
            for msg_type in self._message_types.values()
            if msg_type in BYZZ_MUTATE_METHODS
        ]
        existing_keys = {(seq, to_node, message_type) for seq, to_node, message_type, _ in self.byzz_rules}
        choices = [
            (seq, to_node, message_type)
            for seq in range(self.byzz_min_seq, self.byzz_max_seq + 1)
            for to_node in range(self.num_nodes)
            if to_node not in self.byzz_nodes
            for message_type in supported_message_types
            if (seq, to_node, message_type) not in existing_keys
        ]
        selected = random.sample(choices, min(to_add, len(choices)))
        for c in selected:
            method = self._random_byzz_method(c[2], include_noop=False)
            self.byzz_rules.add((*c, method))

    def _sample_byzz_rules(self):
        if self.mode in ["none", "random"]:
            return
        self.byzz_rules = set()
        self.add_random_byzz_rules(to_add=self.init_num_rules)

    def mutate_self(self, force=False):
        if self.mode != "sparse_rules":
            return
        if self.byzz_rules is None:
            self.byzz_rules = set()

        op = random.choice(["modify", "add", "delete"])
        if force and not self.byzz_rules:
            op = "add"

        if op == "modify":
            if not self.byzz_rules:
                self.add_random_byzz_rules(to_add=1)
                return
            rule_to_modify = random.choice(list(self.byzz_rules))
            self.byzz_rules.discard(rule_to_modify)
            new_method = self._random_byzz_method(
                rule_to_modify[2],
                exclude=rule_to_modify[3],
                include_noop=True,
            )
            self.byzz_rules.add(rule_to_modify[:-1] + (new_method,))
        elif op == "add":
            prev_len = len(self.byzz_rules)
            self.add_random_byzz_rules(to_add=1)
            if len(self.byzz_rules) == prev_len and self.byzz_rules:
                self.mutate_self(force=True)
        elif op == "delete":
            if not self.byzz_rules:
                self.add_random_byzz_rules(to_add=1)
                return
            self.byzz_rules.discard(random.choice(list(self.byzz_rules)))

    def mate_with(self, other: "ByzzEncoding"):
        if self.mode != other.mode:
            raise ValueError(
                f"ByzzEncoding mode mismatch: self={self.mode}, other={other.mode}"
            )
        if self.mode != "sparse_rules":
            return

        child1 = set(self.byzz_rules or set())
        child2 = set(other.byzz_rules or set())

        if child1 and child2:
            rule1 = random.choice(list(child1))
            rule2 = random.choice(list(child2))
            child1.remove(rule1)
            child2.remove(rule2)
            child1.add(rule2)
            child2.add(rule1)

        self.byzz_rules = child1
        other.byzz_rules = child2

    def to_dict(self):
        res = {
            "mode": self.mode,
        }
        if self.byzz_rules is not None:
            res["byzz_rules"] = [
                {
                    "seq": b[0],
                    "to_node": b[1],
                    "message_type": b[2].__name__,
                    "mutation_method": b[3],
                }
                for b in self.byzz_rules
            ]
        return res

    def to_yaml(self):
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)


class PartitionEncoding:
    partition_modes = [
        "none",  # no partition
        "random_bipart",  # randomly partition into two groups
        "bi_part_groups",  # partition into two groups
        # TODO: 目前是把partition的seq和duration固定，作为初始化参数，后续也可以作为encoding一部分
    ]

    def __init__(self, mode, num_nodes, partition_seq, partition_duration):
        if mode not in self.partition_modes:
            raise ValueError(f"Invalid partition mode: {mode}")
        self.mode = mode
        self.partition_seq = partition_seq
        self.partition_duration = partition_duration
        self.num_nodes = num_nodes
        self.partition = None  # list of 0/1, length = number_of_nodes
        self._sample_partition()

    def _sample_partition(self):
        if self.mode in ["none", "random_bipart"]:
            return
        elif self.mode == "bi_part_groups":
            # 随机shuffle，然后随机cut
            nodes = list(range(self.num_nodes))
            random.shuffle(nodes)
            cut = random.randint(1, self.num_nodes - 1)
            self.partition = [0] * self.num_nodes
            for i, idx in enumerate(nodes):
                if i < cut:
                    self.partition[idx] = 0
                else:
                    self.partition[idx] = 1
        else:
            raise ValueError(f"Invalid partition mode: {self.mode}")

    def mutate_self(self, force=False):
        if self.mode != "bi_part_groups" or self.partition is None:
            return
        flip_idx = random.randint(0, len(self.partition) - 1)
        self.partition[flip_idx] = 1 - self.partition[flip_idx]

    def mate_with(self, other: "PartitionEncoding"):
        if self.mode != other.mode:
            raise ValueError(
                f"PartitionEncoding mode mismatch: self={self.mode}, other={other.mode}"
            )
        if self.mode != "bi_part_groups":
            return
        if self.partition is None or other.partition is None:
            return

        new_partition_1 = []
        new_partition_2 = []
        for value1, value2 in zip(self.partition, other.partition):
            if value1 == value2:
                new_partition_1.append(value1)
                new_partition_2.append(value2)
            elif random.random() < 0.5:
                new_partition_1.append(value1)
                new_partition_2.append(value2)
            else:
                new_partition_1.append(value2)
                new_partition_2.append(value1)

        self.partition = new_partition_1
        other.partition = new_partition_2

    def to_dict(self):
        res = {
            "mode": self.mode,
            "partition_seq": self.partition_seq,
            "partition_duration": self.partition_duration,
        }
        if self.partition is not None:
            res["partition"] = self.partition
        return res

    def to_yaml(self):
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)


class DelayEncoding:
    delay_modes = [
        "none",  # no delay
        "random",  # random delay
        "dense_rules",  # <from, to, message_type> -> delay
        "dense_seq_rules",  # <seq, from, to, message_type> -> delay
        "sparse_rules",  # a set of rules: (seq, from, to, message_type) -> delay
    ]

    def __init__(
        self,
        mode,
        num_nodes,
        delay_min,
        delay_max,
        byzz_min_seq,
        byzz_max_seq,
        init_num_rules=5,
    ):
        if mode not in self.delay_modes:
            raise ValueError(f"Invalid delay mode: {mode}")

        self.num_nodes = num_nodes
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.byzz_min_seq = byzz_min_seq
        self.byzz_max_seq = byzz_max_seq
        self.init_num_rules = init_num_rules

        self.mode = mode
        self.delay_constraints = None
        self._sample_dealy_rules()

    def _random_delay(self, exclude=None):
        delay = random.randint(self.delay_min, self.delay_max)
        if exclude is not None and self.delay_max > self.delay_min:
            while delay == exclude:
                delay = random.randint(self.delay_min, self.delay_max)
        return delay

    def _sample_dealy_rules(self):
        if self.mode in ["none", "random"]:
            return
        if self.mode == "dense_rules":
            self.delay_constraints = {}
            for from_node in range(self.num_nodes):
                for to_node in range(self.num_nodes):
                    if from_node == to_node:
                        continue
                    for message_type in MESSAGE_TYPE_MAP.values():
                        delay = random.randint(self.delay_min, self.delay_max)
                        self.delay_constraints[
                            (from_node, to_node, message_type.__name__)
                        ] = delay
        elif self.mode == "dense_seq_rules":
            self.delay_constraints = {}
            for seq in range(self.byzz_min_seq, self.byzz_max_seq + 1):
                for from_node in range(self.num_nodes):
                    for to_node in range(self.num_nodes):
                        if from_node == to_node:
                            continue
                        for message_type in MESSAGE_TYPE_MAP.values():
                            delay = random.randint(self.delay_min, self.delay_max)
                            self.delay_constraints[
                                (seq, from_node, to_node, message_type.__name__)
                            ] = delay
        elif self.mode == "sparse_rules":
            self.delay_constraints = {}
            self.add_random_sparse_delay_rules(to_add=self.init_num_rules)
        else:
            raise ValueError(f"Invalid delay mode: {self.mode}")

    def add_random_sparse_delay_rules(self, to_add=1):
        if self.mode != "sparse_rules":
            return
        if self.delay_constraints is None:
            self.delay_constraints = {}
        choices = [
            (seq, from_node, to_node, message_type.__name__)
            for seq in range(self.byzz_min_seq, self.byzz_max_seq + 1)
            for from_node in range(self.num_nodes)
            for to_node in range(self.num_nodes)
            if from_node != to_node
            for message_type in MESSAGE_TYPE_MAP.values()
            if (seq, from_node, to_node, message_type.__name__)
            not in self.delay_constraints
        ]
        selected = random.sample(choices, min(to_add, len(choices)))
        for choice in selected:
            self.delay_constraints[choice] = self._random_delay()

    def _mutate_dense_mapping(self):
        if not self.delay_constraints:
            return

        original_constraints = dict(self.delay_constraints)

        keys = sorted(self.delay_constraints.keys())
        values = [self.delay_constraints[k] for k in keys]

        tools.mutGaussian(
            values,
            mu=0,
            sigma=(self.delay_max - self.delay_min) / 100.0,
            indpb=1.0 / len(values),
        )

        values = [
            int(round(max(self.delay_min, min(self.delay_max, v))))
            for v in values
        ]

        self.delay_constraints = {
            k: v for k, v in zip(keys, values)
        }
        if self.delay_constraints == original_constraints:
            key = random.choice(keys)
            self.delay_constraints[key] = self._random_delay(
                exclude=self.delay_constraints[key]
            )

    def _mutate_sparse_rules(self):
        if self.delay_constraints is None:
            self.delay_constraints = {}

        op = random.choice(["modify", "add", "delete"])

        if op == "modify":
            if not self.delay_constraints:
                self.add_random_sparse_delay_rules(to_add=1)
                return
            key = random.choice(list(self.delay_constraints.keys()))
            self.delay_constraints[key] = self._random_delay(
                exclude=self.delay_constraints[key]
            )
        elif op == "add":
            prev_len = len(self.delay_constraints)
            self.add_random_sparse_delay_rules(to_add=1)
            if len(self.delay_constraints) == prev_len and self.delay_constraints:
                key = random.choice(list(self.delay_constraints.keys()))
                self.delay_constraints[key] = self._random_delay(
                    exclude=self.delay_constraints[key]
                )
        elif op == "delete":
            if not self.delay_constraints:
                self.add_random_sparse_delay_rules(to_add=1)
                return
            key = random.choice(list(self.delay_constraints.keys()))
            del self.delay_constraints[key]

    def mutate_self(self, force=False):
        if self.mode in ["none", "random"]:
            return
        if self.mode in ["dense_rules", "dense_seq_rules"]:
            self._mutate_dense_mapping()
        elif self.mode == "sparse_rules":
            self._mutate_sparse_rules()
        else:
            raise ValueError(f"Invalid delay mode: {self.mode}")

    def _mate_dense_mapping(self, other):
        keys1 = sorted((self.delay_constraints or {}).keys())
        keys2 = sorted((other.delay_constraints or {}).keys())
        if keys1 != keys2:
            raise ValueError("Dense delay encoding keys must match for crossover")
        if not keys1:
            return

        values1 = [self.delay_constraints[key] for key in keys1]
        values2 = [other.delay_constraints[key] for key in keys2]
        tools.cxSimulatedBinaryBounded(
            values1,
            values2,
            eta=3.0,
            low=self.delay_min,
            up=self.delay_max,
        )
        values1 = [
            int(round(max(self.delay_min, min(self.delay_max, value))))
            for value in values1
        ]
        values2 = [
            int(round(max(self.delay_min, min(self.delay_max, value))))
            for value in values2
        ]
        self.delay_constraints = {
            key: value for key, value in zip(keys1, values1)
        }
        other.delay_constraints = {
            key: value for key, value in zip(keys2, values2)
        }

    def _mate_sparse_rules(self, other):
        child1 = dict(self.delay_constraints or {})
        child2 = dict(other.delay_constraints or {})

        if child1 and child2:
            key1 = random.choice(list(child1.keys()))
            key2 = random.choice(list(child2.keys()))
            value1 = child1.pop(key1)
            value2 = child2.pop(key2)
            child1[key2] = value2
            child2[key1] = value1

        self.delay_constraints = child1
        other.delay_constraints = child2

    def mate_with(self, other):
        if self.mode != other.mode:
            raise ValueError(
                f"DelayEncoding mode mismatch: self={self.mode}, other={other.mode}"
            )
        if self.mode in ["none", "random"]:
            return
        if self.mode in ["dense_rules", "dense_seq_rules"]:
            self._mate_dense_mapping(other)
        elif self.mode == "sparse_rules":
            self._mate_sparse_rules(other)
        else:
            raise ValueError(f"Invalid delay mode: {self.mode}")
    
    def to_dict(self):
        res = {
            "mode": self.mode,
        }
        if self.delay_constraints is not None:
            if self.mode == "dense_rules":
                res["delays"] = [
                    {
                        "from_node": from_node,
                        "to_node": to_node,
                        "message_type": message_type,
                        "delay": delay,
                    }
                    for (
                        from_node,
                        to_node,
                        message_type,
                    ), delay in self.delay_constraints.items()
                ]
            elif self.mode == "dense_seq_rules":
                res["delays"] = [
                    {
                        "seq": seq,
                        "from_node": from_node,
                        "to_node": to_node,
                        "message_type": message_type,
                        "delay": delay,
                    }
                    for (
                        seq,
                        from_node,
                        to_node,
                        message_type,
                    ), delay in self.delay_constraints.items()
                ]
            elif self.mode == "sparse_rules":
                res["delays"] = [
                    {
                        "seq": seq,
                        "from_node": from_node,
                        "to_node": to_node,
                        "message_type": message_type,
                        "delay": delay,
                    }
                    for (
                        seq,
                        from_node,
                        to_node,
                        message_type,
                    ), delay in self.delay_constraints.items()
                ]
            else:
                raise ValueError(f"Invalid delay mode: {self.mode}")
        return res

    def to_yaml(self):
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)


class ComposeEncoding(BaseEncoding):
    def __init__(
        self,
        byzz_encoding: ByzzEncoding,
        delay_encoding: DelayEncoding,
        partition_encoding: PartitionEncoding,
    ):
        self.byzz_encoding = byzz_encoding
        self.byzz_mode = byzz_encoding.mode
        self.delay_encoding = delay_encoding
        self.delay_mode = delay_encoding.mode
        self.partition_encoding = partition_encoding
        self.partition_mode = partition_encoding.mode
        
        # 看自己的三个部分哪些是none或者random的，在mutate和mate的时候不考虑
        self.active_components = []
        if self.byzz_mode not in ["none", "random"]:
            self.active_components.append("byzz")
        if self.delay_mode not in ["none", "random"]:
            self.active_components.append("delay")
        if self.partition_mode not in ["none", "random_bipart"]:
            self.active_components.append("partition")
        
    def to_dict(self):
        return {
            "ByzzEncoding": self.byzz_encoding.to_dict(),
            "DelayEncoding": self.delay_encoding.to_dict(),
            "PartitionEncoding": self.partition_encoding.to_dict(),
        }

    @staticmethod
    def _format_message_type(message_type):
        if isinstance(message_type, str):
            return message_type
        return message_type.__name__

    @classmethod
    def _format_delay_key(cls, key):
        if len(key) == 3:
            from_node, to_node, message_type = key
            return (
                f"from_node={from_node}, to_node={to_node}, "
                f"message_type={cls._format_message_type(message_type)}"
            )
        if len(key) == 4:
            seq, from_node, to_node, message_type = key
            return (
                f"seq={seq}, from_node={from_node}, to_node={to_node}, "
                f"message_type={cls._format_message_type(message_type)}"
            )
        return str(key)

    @classmethod
    def _format_byzz_key(cls, key):
        seq, to_node, message_type = key
        return (
            f"seq={seq}, to_node={to_node}, "
            f"message_type={cls._format_message_type(message_type)}"
        )

    def _check_mode_compatibility(self, other):
        self_modes = (self.byzz_mode, self.delay_mode, self.partition_mode)
        other_modes = (other.byzz_mode, other.delay_mode, other.partition_mode)
        if self_modes != other_modes:
            raise ValueError(
                f"ComposeEncoding mode mismatch: self={self_modes}, other={other_modes}"
            )

    def _diff_partition(self, other):
        if self.partition_mode in ["none", "random_bipart"]:
            return []

        current = self.partition_encoding.partition or []
        previous = other.partition_encoding.partition or []
        changed = [
            (idx, old_value, new_value)
            for idx, (old_value, new_value) in enumerate(zip(previous, current))
            if old_value != new_value
        ]
        if not changed:
            return []

        lines = [f"PartitionEncoding: {len(changed)} node(s) changed"]
        for idx, old_value, new_value in changed:
            lines.append(f"  node {idx}: {old_value} -> {new_value}")
        return lines

    def _diff_delay(self, other):
        if self.delay_mode in ["none", "random"]:
            return []

        current = self.delay_encoding.delay_constraints or {}
        previous = other.delay_encoding.delay_constraints or {}

        previous_keys = set(previous.keys())
        current_keys = set(current.keys())

        removed = sorted(previous_keys - current_keys)
        added = sorted(current_keys - previous_keys)
        modified = sorted(
            key for key in previous_keys & current_keys if previous[key] != current[key]
        )

        if not (removed or added or modified):
            return []

        lines = ["DelayEncoding:"]
        for key in modified:
            lines.append(
                f"  modified {self._format_delay_key(key)}: "
                f"{previous[key]} -> {current[key]}"
            )
        for key in added:
            lines.append(
                f"  added {self._format_delay_key(key)}: {current[key]}"
            )
        for key in removed:
            lines.append(
                f"  removed {self._format_delay_key(key)}: {previous[key]}"
            )
        return lines

    def _diff_byzz(self, other):
        if self.byzz_mode in ["none", "random"]:
            return []

        current_rules = self.byzz_encoding.byzz_rules or set()
        previous_rules = other.byzz_encoding.byzz_rules or set()

        current = {
            (seq, to_node, self._format_message_type(message_type)): method
            for seq, to_node, message_type, method in current_rules
        }
        previous = {
            (seq, to_node, self._format_message_type(message_type)): method
            for seq, to_node, message_type, method in previous_rules
        }

        previous_keys = set(previous.keys())
        current_keys = set(current.keys())

        removed = sorted(previous_keys - current_keys)
        added = sorted(current_keys - previous_keys)
        modified = sorted(
            key for key in previous_keys & current_keys if previous[key] != current[key]
        )

        if not (removed or added or modified):
            return []

        lines = ["ByzzEncoding:"]
        for key in modified:
            lines.append(
                f"  modified {self._format_byzz_key(key)}: "
                f"{previous[key]} -> {current[key]}"
            )
        for key in added:
            lines.append(
                f"  added {self._format_byzz_key(key)}: {current[key]}"
            )
        for key in removed:
            lines.append(
                f"  removed {self._format_byzz_key(key)}: {previous[key]}"
            )
        return lines

    def diff(self, other):
        self._check_mode_compatibility(other)

        lines = []
        lines.extend(self._diff_partition(other))
        lines.extend(self._diff_delay(other))
        lines.extend(self._diff_byzz(other))

        if not lines:
            return "No encoded differences."
        return "\n".join(lines)
        
    def to_yaml(self):
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)
    
    @staticmethod
    def mate(ind1, ind2):
        return _mate_composed_encoding(ind1, ind2)

    @staticmethod
    def mutate(ind):
        return _mutate_composed_encoding(ind)
    
    
    @staticmethod
    def sample(configs):
        required_keys = [
            "byzz_mode",
            "delay_mode",
            "partition_mode",
            "number_of_nodes",
            "min_delay_ms",
            "max_delay_ms",
            "byzz_min_seq",
            "byzz_max_seq",
            "partition_seq",
            "partition_duration",
            "byzz_nodes",
        ]
        for key in required_keys:
            if key not in configs:
                raise ValueError(f"Missing required config key: {key}")

        

        byzz_encoding = ByzzEncoding(
            mode=configs["byzz_mode"],
            num_nodes=configs["number_of_nodes"],
            byzz_nodes=configs["byzz_nodes"],
            byzz_min_seq=configs["byzz_min_seq"],
            byzz_max_seq=configs["byzz_max_seq"],
            init_num_rules=configs.get("byzz_init_num_rules", 5),
        )

        delay_encoding = DelayEncoding(
            mode=configs["delay_mode"],
            num_nodes=configs["number_of_nodes"],
            delay_min=configs["min_delay_ms"],
            delay_max=configs["max_delay_ms"],
            byzz_min_seq=configs["byzz_min_seq"],
            byzz_max_seq=configs["byzz_max_seq"],
            init_num_rules=configs.get("delay_init_num_rules", 5),
        )

        partition_encoding = PartitionEncoding(
            mode=configs["partition_mode"],
            num_nodes=configs["number_of_nodes"],
            partition_seq=configs["partition_seq"],
            partition_duration=configs["partition_duration"],
        )

        return ComposeEncoding(
            byzz_encoding=byzz_encoding,
            delay_encoding=delay_encoding,
            partition_encoding=partition_encoding,
        )




def _mutate_composed_encoding(ind: ComposeEncoding):
    if not ind.active_components:
        return (ind,)

    mutated_components = []
    for component in ind.active_components:
        if random.random() >= 0.5:
            continue
        if component == "partition":
            ind.partition_encoding.mutate_self()
        elif component == "delay":
            ind.delay_encoding.mutate_self()
        elif component == "byzz":
            ind.byzz_encoding.mutate_self()
        mutated_components.append(component)

    if not mutated_components:
        component = random.choice(ind.active_components)
        if component == "partition":
            ind.partition_encoding.mutate_self(force=True)
        elif component == "delay":
            ind.delay_encoding.mutate_self(force=True)
        elif component == "byzz":
            ind.byzz_encoding.mutate_self(force=True)

    return (ind,)

def _mate_composed_encoding(ind1: ComposeEncoding, ind2: ComposeEncoding):
    ind1._check_mode_compatibility(ind2)

    if "partition" in ind1.active_components:
        ind1.partition_encoding.mate_with(ind2.partition_encoding)
    if "delay" in ind1.active_components:
        ind1.delay_encoding.mate_with(ind2.delay_encoding)
    if "byzz" in ind1.active_components:
        ind1.byzz_encoding.mate_with(ind2.byzz_encoding)

    return ind1, ind2


# ---------------------------------------------------------------------------------------------------------------


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

        self._message_types = MESSAGE_TYPE_MAP

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
                # 在所有mutation中选，但是去掉do_nothing
                method = random.choice(
                    [m for m in BYZZ_MUTATE_METHODS[c[2]] if m != "do_nothing"]
                )
                self.byzz_rules.add((*c, method))
        else:
            selected = random.sample(choices, to_add)
            for c in selected:
                method = random.choice(
                    [m for m in BYZZ_MUTATE_METHODS[c[2]] if m != "do_nothing"]
                )
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
        # 只交换一条规则
        # start with simple copies
        child1 = set(rules1)
        child2 = set(rules2)

        # only perform a swap when both parents have at least one rule
        if child1 and child2:
            r1 = random.choice(list(child1))
            r2 = random.choice(list(child2))
            # swap the two rules
            child1.remove(r1)
            child2.remove(r2)
            child1.add(r2)
            child2.add(r1)

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
    for mode in DelayEncoding.delay_modes:
        delay = DelayEncoding(
            mode,
            num_nodes=3,
            delay_min=10,
            delay_max=100,
            byzz_min_seq=5,
            byzz_max_seq=7,
        )
        print(f" --- Mode: {mode} --- ")
        print(delay.to_yaml())

    for mode in PartitionEncoding.partition_modes:
        partition = PartitionEncoding(
            mode,
            num_nodes=10,
            partition_seq=5,
            partition_duration=10,
        )
        print(f" --- Mode: {mode} --- ")
        print(partition.to_yaml())

    for mode in ByzzEncoding.byzz_modes:
        byzz = ByzzEncoding(
            mode,
            num_nodes=3,
            byzz_nodes=[1],
            byzz_min_seq=5,
            byzz_max_seq=7,
            init_num_rules=5,
        )
        print(f" --- Mode: {mode} --- ")
        print(byzz.to_yaml())
        
        
    # 测试一下composeencoding
    configs = {
        "byzz_mode": "sparse_rules",
        "delay_mode": "sparse_rules",
        "partition_mode": "bi_part_groups",
        "number_of_nodes": 5,
        "min_delay_ms": 10,
        "max_delay_ms": 100,
        "byzz_min_seq": 5,
        "byzz_max_seq": 7,
        "partition_seq": 6,
        "partition_duration": 10,
        "byzz_init_num_rules": 5,
        "delay_init_num_rules": 5,
        "byzz_nodes": [3],
    }
    
    compose = ComposeEncoding.sample(configs)
    print(" --- ComposeEncoding initial --- ")
    print(compose.to_yaml())

    for i in range(3):
        before = copy.deepcopy(compose)
        ComposeEncoding.mutate(compose)
        print(f" --- ComposeEncoding mutate round {i + 1} --- ")
        print(compose.diff(before))
        print(compose.to_yaml())

    mate_left = ComposeEncoding.sample(configs)
    mate_right = ComposeEncoding.sample(configs)
    mate_left_before = copy.deepcopy(mate_left)
    mate_right_before = copy.deepcopy(mate_right)

    ComposeEncoding.mate(mate_left, mate_right)

    print(" --- ComposeEncoding mate left diff --- ")
    print(mate_left.diff(mate_left_before))
    print(mate_left.to_yaml())

    print(" --- ComposeEncoding mate right diff --- ")
    print(mate_right.diff(mate_right_before))
    print(mate_right.to_yaml())
        
        
    # 测试一下mate
