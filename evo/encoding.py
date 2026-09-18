from pathlib import Path
import copy
import numpy as np
from deap import tools
import sys
import random
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rocket_controller.strategies.utils import (
    BYZZ_MUTATE_METHODS,
    build_byzz_mutate_methods,
)
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

SPARSE_SET_RULES = "sparse_set_rules"
SPARSE_SEQ_PROPOSAL_RULES = "sparse_seq_proposal_rules"
SPARSE_SEQ_PROPOSAL_SET_RULES = "sparse_seq_proposal_set_rules"
OPEN_PROPOSAL_SEQ = -1
OPEN_LATE_PART_GROUPS = "open_late_part_groups"


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
        SPARSE_SET_RULES,  # (seq, to_nodes, message_type) -> mutation method
        SPARSE_SEQ_PROPOSAL_RULES,  # (seq, pro_seq, to_node, message_type) -> mutation method
        # (seq, pro_seq, to_nodes, message_type) -> mutation method
        SPARSE_SEQ_PROPOSAL_SET_RULES,
    ]
    _message_types = MESSAGE_TYPE_MAP

    def __init__(
        self,
        mode,
        num_nodes,
        byzz_nodes,
        byzz_min_seq,
        byzz_max_seq,
        init_num_rules=5,
        max_proposal_seq=5,
        byzz_enabled_mutation_methods=None,
        byzz_disabled_mutation_methods=None,
    ):
        if mode not in self.byzz_modes:
            raise ValueError(f"Invalid byzz mode: {mode}")
        self.mode = mode
        self.num_nodes = num_nodes
        self.byzz_nodes = byzz_nodes or []
        self.byzz_min_seq = byzz_min_seq
        self.byzz_max_seq = byzz_max_seq
        self.byzz_mutate_methods = build_byzz_mutate_methods(
            enabled_methods=byzz_enabled_mutation_methods,
            disabled_methods=byzz_disabled_mutation_methods,
        )
        self.max_proposal_seq = int(max_proposal_seq)
        if self.max_proposal_seq < 0:
            raise ValueError("max_proposal_seq must be non-negative")
        self.byzz_rules = None
        self.init_num_rules = init_num_rules
        self._sample_byzz_rules()

    def _random_byzz_method(self, message_type, exclude=None, include_noop=False):
        methods = self.byzz_mutate_methods[message_type]
        if not include_noop:
            methods = [m for m in methods if m != "do_nothing"]
        if exclude is not None and len(methods) > 1:
            methods = [m for m in methods if m != exclude]
        return random.choice(methods)

    def _supported_byzz_message_types(self):
        return [
            msg_type
            for msg_type in self._message_types.values()
            if msg_type in self.byzz_mutate_methods
            and any(m != "do_nothing" for m in self.byzz_mutate_methods[msg_type])
        ]

    def _honest_nodes(self):
        return [node for node in range(self.num_nodes) if node not in self.byzz_nodes]

    @staticmethod
    def _random_subset(candidates):
        if not candidates:
            return tuple()
        size = random.randint(1, len(candidates))
        return tuple(sorted(random.sample(candidates, size)))

    def _repair_receiver_set(self, to_nodes):
        allowed = set(self._honest_nodes())
        repaired = sorted({int(node) for node in to_nodes if int(node) in allowed})
        if repaired:
            return tuple(repaired)
        if not allowed:
            return tuple()
        return (random.choice(sorted(allowed)),)

    def _random_receiver_set(self, exclude=None):
        allowed = self._honest_nodes()
        if not allowed:
            return tuple()
        receiver_set = self._random_subset(allowed)
        if exclude is not None and len(allowed) > 1:
            attempts = 0
            while receiver_set == exclude and attempts < 20:
                receiver_set = self._random_subset(allowed)
                attempts += 1
        return self._repair_receiver_set(receiver_set)

    def _random_byzz_key(self):
        supported_message_types = self._supported_byzz_message_types()
        if not supported_message_types:
            return None

        seq = random.randint(self.byzz_min_seq, self.byzz_max_seq)
        message_type = random.choice(supported_message_types)
        if self.mode == "sparse_rules":
            candidates = self._honest_nodes()
            if not candidates:
                return None
            return (seq, random.choice(candidates), message_type)
        if self.mode == SPARSE_SEQ_PROPOSAL_RULES:
            candidates = self._honest_nodes()
            if not candidates:
                return None
            pro_seq = random.randint(OPEN_PROPOSAL_SEQ, self.max_proposal_seq)
            return (seq, pro_seq, random.choice(candidates), message_type)
        if self.mode == SPARSE_SET_RULES:
            receiver_set = self._random_receiver_set()
            if not receiver_set:
                return None
            return (seq, receiver_set, message_type)
        if self.mode == SPARSE_SEQ_PROPOSAL_SET_RULES:
            receiver_set = self._random_receiver_set()
            if not receiver_set:
                return None
            pro_seq = random.randint(OPEN_PROPOSAL_SEQ, self.max_proposal_seq)
            return (seq, pro_seq, receiver_set, message_type)
        return None

    def add_random_byzz_rules(self, to_add=1):
        if self.mode not in [
            "sparse_rules",
            SPARSE_SET_RULES,
            SPARSE_SEQ_PROPOSAL_RULES,
            SPARSE_SEQ_PROPOSAL_SET_RULES,
        ]:
            return
        if self.byzz_rules is None:
            self.byzz_rules = set()

        supported_message_types = self._supported_byzz_message_types()
        if self.mode == "sparse_rules":
            existing_keys = {
                (seq, to_node, message_type)
                for seq, to_node, message_type, _ in self.byzz_rules
            }
            choices = [
                (seq, to_node, message_type)
                for seq in range(self.byzz_min_seq, self.byzz_max_seq + 1)
                for to_node in range(self.num_nodes)
                if to_node not in self.byzz_nodes
                for message_type in supported_message_types
                if (seq, to_node, message_type) not in existing_keys
            ]
        elif self.mode == SPARSE_SEQ_PROPOSAL_RULES:
            existing_keys = {
                (seq, pro_seq, to_node, message_type)
                for seq, pro_seq, to_node, message_type, _ in self.byzz_rules
            }
            choices = [
                (seq, pro_seq, to_node, message_type)
                for seq in range(self.byzz_min_seq, self.byzz_max_seq + 1)
                for pro_seq in range(OPEN_PROPOSAL_SEQ, self.max_proposal_seq + 1)
                for to_node in range(self.num_nodes)
                if to_node not in self.byzz_nodes
                for message_type in supported_message_types
                if (seq, pro_seq, to_node, message_type) not in existing_keys
            ]
        elif self.mode == SPARSE_SET_RULES:
            existing_keys = {
                (seq, to_nodes, message_type)
                for seq, to_nodes, message_type, _ in self.byzz_rules
            }
            # Receiver-set rules have a combinatorial key space. Sampling directly
            # avoids materializing all possible node subsets.
            choices = []
            attempts = 0
            max_attempts = max(100, to_add * 50)
            while len(choices) < to_add and attempts < max_attempts:
                attempts += 1
                key = self._random_byzz_key()
                if key is None or key in existing_keys or key in choices:
                    continue
                choices.append(key)
        elif self.mode == SPARSE_SEQ_PROPOSAL_SET_RULES:
            existing_keys = {
                (seq, pro_seq, to_nodes, message_type)
                for seq, pro_seq, to_nodes, message_type, _ in self.byzz_rules
            }
            # Receiver-set rules have a combinatorial key space. Sampling directly
            # avoids materializing all possible node subsets.
            choices = []
            attempts = 0
            max_attempts = max(100, to_add * 50)
            while len(choices) < to_add and attempts < max_attempts:
                attempts += 1
                key = self._random_byzz_key()
                if key is None or key in existing_keys or key in choices:
                    continue
                choices.append(key)
        selected = random.sample(choices, min(to_add, len(choices)))
        for c in selected:
            method = self._random_byzz_method(c[-1], include_noop=False)
            self.byzz_rules.add((*c, method))

    def _sample_byzz_rules(self):
        if self.mode in ["none", "random"]:
            return
        self.byzz_rules = set()
        self.add_random_byzz_rules(to_add=self.init_num_rules)

    def _mutate_set_rule_key(self, rule):
        seq, pro_seq, to_nodes, message_type, method = rule
        op = random.choice(["seq", "pro_seq", "to_nodes", "message_type", "method"])
        if op == "seq":
            seq = random.randint(self.byzz_min_seq, self.byzz_max_seq)
        elif op == "pro_seq":
            pro_seq = random.randint(OPEN_PROPOSAL_SEQ, self.max_proposal_seq)
        elif op == "to_nodes":
            to_nodes = list(to_nodes)
            if random.random() < 0.5 and len(to_nodes) > 1:
                to_nodes.remove(random.choice(to_nodes))
            else:
                candidates = [node for node in self._honest_nodes() if node not in to_nodes]
                if candidates:
                    to_nodes.append(random.choice(candidates))
                elif to_nodes:
                    to_nodes.remove(random.choice(to_nodes))
            to_nodes = self._repair_receiver_set(to_nodes)
        elif op == "message_type":
            candidates = [
                msg_type
                for msg_type in self._message_types.values()
                if msg_type in self.byzz_mutate_methods and msg_type != message_type
                and any(m != "do_nothing" for m in self.byzz_mutate_methods[msg_type])
            ]
            if candidates:
                message_type = random.choice(candidates)
                method = self._random_byzz_method(message_type, include_noop=False)
        elif op == "method":
            method = self._random_byzz_method(
                message_type,
                exclude=method,
                include_noop=True,
            )
        to_nodes = self._repair_receiver_set(to_nodes)
        if not to_nodes:
            return None
        if method not in self.byzz_mutate_methods[message_type]:
            method = self._random_byzz_method(message_type, include_noop=False)
        return (seq, pro_seq, to_nodes, message_type, method)

    def _mutate_receiver_set_rule_key(self, rule):
        seq, to_nodes, message_type, method = rule
        op = random.choice(["seq", "to_nodes", "message_type", "method"])
        if op == "seq":
            seq = random.randint(self.byzz_min_seq, self.byzz_max_seq)
        elif op == "to_nodes":
            to_nodes = list(to_nodes)
            if random.random() < 0.5 and len(to_nodes) > 1:
                to_nodes.remove(random.choice(to_nodes))
            else:
                candidates = [node for node in self._honest_nodes() if node not in to_nodes]
                if candidates:
                    to_nodes.append(random.choice(candidates))
                elif to_nodes:
                    to_nodes.remove(random.choice(to_nodes))
            to_nodes = self._repair_receiver_set(to_nodes)
        elif op == "message_type":
            candidates = [
                msg_type
                for msg_type in self._message_types.values()
                if msg_type in self.byzz_mutate_methods and msg_type != message_type
                and any(m != "do_nothing" for m in self.byzz_mutate_methods[msg_type])
            ]
            if candidates:
                message_type = random.choice(candidates)
                method = self._random_byzz_method(message_type, include_noop=False)
        elif op == "method":
            method = self._random_byzz_method(
                message_type,
                exclude=method,
                include_noop=True,
            )
        to_nodes = self._repair_receiver_set(to_nodes)
        if not to_nodes:
            return None
        if method not in self.byzz_mutate_methods[message_type]:
            method = self._random_byzz_method(message_type, include_noop=False)
        return (seq, to_nodes, message_type, method)

    def mutate_self(self, force=False):
        if self.mode not in [
            "sparse_rules",
            SPARSE_SET_RULES,
            SPARSE_SEQ_PROPOSAL_RULES,
            SPARSE_SEQ_PROPOSAL_SET_RULES,
        ]:
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
            if self.mode == SPARSE_SET_RULES:
                mutated = self._mutate_receiver_set_rule_key(rule_to_modify)
                if mutated is not None:
                    self.byzz_rules.add(mutated)
            elif self.mode == SPARSE_SEQ_PROPOSAL_SET_RULES:
                mutated = self._mutate_set_rule_key(rule_to_modify)
                if mutated is not None:
                    self.byzz_rules.add(mutated)
            else:
                new_method = self._random_byzz_method(
                    rule_to_modify[-2],
                    exclude=rule_to_modify[-1],
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
        if self.mode not in [
            "sparse_rules",
            SPARSE_SET_RULES,
            SPARSE_SEQ_PROPOSAL_RULES,
            SPARSE_SEQ_PROPOSAL_SET_RULES,
        ]:
            return

        child1 = set(self.byzz_rules or set())
        child2 = set(other.byzz_rules or set())

        if child1 and child2:
            rule1 = random.choice(list(child1))
            rule2 = random.choice(list(child2))
            child1.remove(rule1)
            child2.remove(rule2)
            if self.mode == SPARSE_SET_RULES:
                child_rule1, child_rule2 = self._crossover_receiver_set_rules(rule1, rule2)
                if child_rule1 is not None:
                    child1.add(child_rule1)
                if child_rule2 is not None:
                    child2.add(child_rule2)
            elif self.mode == SPARSE_SEQ_PROPOSAL_SET_RULES:
                child_rule1, child_rule2 = self._crossover_set_rules(rule1, rule2)
                if child_rule1 is not None:
                    child1.add(child_rule1)
                if child_rule2 is not None:
                    child2.add(child_rule2)
            else:
                child1.add(rule2)
                child2.add(rule1)

        self.byzz_rules = child1
        other.byzz_rules = child2

    def _crossover_receiver_set_rules(self, left, right):
        left_seq, left_to, left_msg, left_method = left
        right_seq, right_to, right_msg, right_method = right

        if random.random() < 0.5:
            left_seq, right_seq = right_seq, left_seq
        if random.random() < 0.5:
            left_msg, right_msg = right_msg, left_msg

        left_to, right_to = self._crossover_node_sets(
            left_to,
            right_to,
            allowed_nodes=self._honest_nodes(),
        )

        if left_method not in self.byzz_mutate_methods[left_msg]:
            left_method = self._random_byzz_method(left_msg, include_noop=False)
        if right_method not in self.byzz_mutate_methods[right_msg]:
            right_method = self._random_byzz_method(right_msg, include_noop=False)

        left_to = self._repair_receiver_set(left_to)
        right_to = self._repair_receiver_set(right_to)
        child_left = (left_seq, left_to, left_msg, left_method) if left_to else None
        child_right = (right_seq, right_to, right_msg, right_method) if right_to else None
        return child_left, child_right

    def _crossover_set_rules(self, left, right):
        left_seq, left_pro_seq, left_to, left_msg, left_method = left
        right_seq, right_pro_seq, right_to, right_msg, right_method = right

        if random.random() < 0.5:
            left_seq, right_seq = right_seq, left_seq
        if random.random() < 0.5:
            left_pro_seq, right_pro_seq = right_pro_seq, left_pro_seq
        if random.random() < 0.5:
            left_msg, right_msg = right_msg, left_msg

        left_to, right_to = self._crossover_node_sets(
            left_to,
            right_to,
            allowed_nodes=self._honest_nodes(),
        )

        if left_method not in self.byzz_mutate_methods[left_msg]:
            left_method = self._random_byzz_method(left_msg, include_noop=False)
        if right_method not in self.byzz_mutate_methods[right_msg]:
            right_method = self._random_byzz_method(right_msg, include_noop=False)

        left_to = self._repair_receiver_set(left_to)
        right_to = self._repair_receiver_set(right_to)
        child_left = (
            (left_seq, left_pro_seq, left_to, left_msg, left_method)
            if left_to
            else None
        )
        child_right = (
            (right_seq, right_pro_seq, right_to, right_msg, right_method)
            if right_to
            else None
        )
        return child_left, child_right

    @staticmethod
    def _crossover_node_sets(left_nodes, right_nodes, allowed_nodes):
        left = set(left_nodes)
        right = set(right_nodes)
        child_left = set(left)
        child_right = set(right)
        for node in allowed_nodes:
            if (node in left) != (node in right) and random.random() < 0.5:
                if node in child_left:
                    child_left.remove(node)
                    child_right.add(node)
                else:
                    child_left.add(node)
                    child_right.discard(node)
        if not child_left and allowed_nodes:
            child_left.add(random.choice(allowed_nodes))
        if not child_right and allowed_nodes:
            child_right.add(random.choice(allowed_nodes))
        return tuple(sorted(child_left)), tuple(sorted(child_right))

    def to_dict(self):
        res = {
            "mode": self.mode,
        }
        if self.byzz_rules is not None:
            byzz_rules = []
            for b in self.byzz_rules:
                if self.mode == "sparse_rules" and len(b) == 4:
                    seq, to_node, message_type, method = b
                    byzz_rules.append(
                        {
                            "seq": seq,
                            "to_node": to_node,
                            "message_type": message_type.__name__,
                            "mutation_method": method,
                        }
                    )
                elif self.mode == SPARSE_SEQ_PROPOSAL_RULES and len(b) == 5:
                    seq, pro_seq, to_node, message_type, method = b
                    byzz_rules.append(
                        {
                            "seq": seq,
                            "pro_seq": pro_seq,
                            "to_node": to_node,
                            "message_type": message_type.__name__,
                            "mutation_method": method,
                        }
                    )
                elif self.mode == SPARSE_SET_RULES and len(b) == 4:
                    seq, to_nodes, message_type, method = b
                    byzz_rules.append(
                        {
                            "seq": seq,
                            "to_nodes": list(to_nodes),
                            "message_type": message_type.__name__,
                            "mutation_method": method,
                        }
                    )
                elif self.mode == SPARSE_SEQ_PROPOSAL_SET_RULES and len(b) == 5:
                    seq, pro_seq, to_nodes, message_type, method = b
                    byzz_rules.append(
                        {
                            "seq": seq,
                            "pro_seq": pro_seq,
                            "to_nodes": list(to_nodes),
                            "message_type": message_type.__name__,
                            "mutation_method": method,
                        }
                    )
                else:
                    raise ValueError(f"Invalid byzz rule format: {b}")
            res["byzz_rules"] = byzz_rules
        return res

    def to_yaml(self):
        return yaml.safe_dump(self.to_dict(), sort_keys=False, allow_unicode=True)


class PartitionEncoding:
    partition_modes = [
        "none",  # no partition
        "random_bipart",  # randomly partition into two groups
        "bi_part_groups",  # partition into two groups
        "flex_bi_part_groups",  # two groups with evolvable seq and duration
        # two groups with evolvable seq/start offset/message type; duration is fixed
        "flex_msg_part_groups",
        # two groups with evolvable seq/start offset; fixed duration, no msg filter
        OPEN_LATE_PART_GROUPS,
    ]
    _message_types = MESSAGE_TYPE_MAP

    def __init__(
        self,
        mode,
        num_nodes,
        partition_seq=5,
        partition_duration=None,
        byzz_min_seq=None,
        byzz_max_seq=None,
        max_partition_duration=1000,
        max_partition_start_after_ms=None,
        start_partition="open",
        init_num_rules=1,
    ):
        if mode not in self.partition_modes:
            raise ValueError(f"Invalid partition mode: {mode}")
        if start_partition not in ["open", "establish"]:
            raise ValueError(f"Invalid start_partition: {start_partition}")
        if max_partition_duration is None:
            max_partition_duration = (
                partition_duration if partition_duration is not None else 1000
            )
        if partition_duration is None:
            partition_duration = max_partition_duration
        self.mode = mode
        self.start_partition = start_partition
        self.partition_seq = int(partition_seq)
        self.partition_duration = int(partition_duration)
        self.init_num_rules = int(init_num_rules)
        self.num_nodes = int(num_nodes)
        self.byzz_min_seq = int(
            byzz_min_seq if byzz_min_seq is not None else partition_seq
        )
        self.byzz_max_seq = int(
            byzz_max_seq if byzz_max_seq is not None else partition_seq
        )
        self.max_partition_duration = int(
            max_partition_duration
            if max_partition_duration is not None
            else partition_duration
        )
        self.max_partition_start_after_ms = int(
            max_partition_start_after_ms
            if max_partition_start_after_ms is not None
            else self.max_partition_duration
        )
        if self.byzz_min_seq > self.byzz_max_seq:
            raise ValueError(
                f"Invalid partition seq range: {self.byzz_min_seq} > {self.byzz_max_seq}"
            )
        if self.init_num_rules <= 0:
            raise ValueError("init_num_rules must be positive")
        if self.max_partition_duration <= 0:
            raise ValueError("max_partition_duration must be positive")
        if self.max_partition_start_after_ms < 0:
            raise ValueError("max_partition_start_after_ms must be non-negative")
        self.partition = None  # legacy compatibility: mirrors the first rule
        self.partition_rules = []
        self._sample_partition_rules()

    @staticmethod
    def _format_message_type(message_type):
        if isinstance(message_type, str):
            return message_type
        return message_type.__name__

    def _random_partition_message_type(self, exclude=None):
        message_types = [msg_type.__name__ for msg_type in self._message_types.values()]
        if exclude is not None and len(message_types) > 1:
            message_types = [msg for msg in message_types if msg != exclude]
        return random.choice(message_types)

    def _build_partition_rule(
        self,
        partition,
        partition_seq,
        partition_duration=None,
        start_after_ms=None,
        message_type=None,
    ):
        rule = {
            "partition_seq": int(partition_seq),
            "partition": [int(value) for value in partition],
        }
        if partition_duration is not None:
            rule["partition_duration"] = int(partition_duration)
        if start_after_ms is not None:
            rule["start_after_ms"] = int(start_after_ms)
        if message_type is not None:
            rule["message_type"] = self._format_message_type(message_type)
        return rule

    def _sync_legacy_partition_fields(self):
        if not self.partition_rules:
            self.partition = None
            return
        first_rule = self.partition_rules[0]
        self.partition_seq = int(first_rule["partition_seq"])
        self.partition_duration = int(
            first_rule.get("partition_duration", self.partition_duration)
        )
        self.partition = list(first_rule["partition"])

    def _sample_partition_groups(self):
        if self.num_nodes < 2:
            raise ValueError("partition modes require at least two nodes")

        nodes = list(range(self.num_nodes))
        random.shuffle(nodes)
        cut = random.randint(1, self.num_nodes - 1)
        partition = [0] * self.num_nodes
        for i, idx in enumerate(nodes):
            if i < cut:
                partition[idx] = 0
            else:
                partition[idx] = 1
        return partition

    @staticmethod
    def _random_int_excluding(low, high, current):
        if low >= high:
            return low

        value = random.randint(low, high)
        while value == current:
            value = random.randint(low, high)
        return value

    def _repair_partition_groups(self, rule):
        partition = rule["partition"]
        if len(set(partition)) > 1:
            return
        if len(partition) < 2:
            raise ValueError("partition rules require at least two nodes")

        flip_idx = random.randint(0, len(partition) - 1)
        partition[flip_idx] = 1 - partition[flip_idx]

    def _repair_partition_rule(self, rule):
        rule["partition_seq"] = int(
            max(self.byzz_min_seq, min(self.byzz_max_seq, rule["partition_seq"]))
        )
        if self.mode in ["flex_msg_part_groups", OPEN_LATE_PART_GROUPS]:
            rule["start_after_ms"] = int(
                max(
                    0,
                    min(
                        self.max_partition_start_after_ms,
                        int(rule.get("start_after_ms", 0)),
                    ),
                )
            )
            if self.mode == "flex_msg_part_groups":
                message_types = {
                    msg_type.__name__ for msg_type in self._message_types.values()
                }
                if "message_type" not in rule:
                    rule["message_type"] = self._random_partition_message_type()
                if rule["message_type"] not in message_types:
                    raise ValueError(
                        f"Invalid partition message_type: {rule['message_type']}"
                    )
            else:
                rule.pop("message_type", None)
            rule.pop("partition_duration", None)
        else:
            rule["partition_duration"] = int(
                max(1, min(self.max_partition_duration, rule["partition_duration"]))
            )
        if len(rule["partition"]) != self.num_nodes:
            raise ValueError(
                f"partition length {len(rule['partition'])} != num_nodes {self.num_nodes}"
            )
        if any(value not in (0, 1) for value in rule["partition"]):
            raise ValueError("partition values must be 0 or 1")
        self._repair_partition_groups(rule)

    def _sample_partition_rules(self):
        if self.mode in ["none", "random_bipart"]:
            return

        if (
            self.mode in ["flex_bi_part_groups", "flex_msg_part_groups", OPEN_LATE_PART_GROUPS]
            and self.init_num_rules > self._max_partition_rule_choices()
        ):
            raise ValueError(
                "partition_init_num_rules cannot exceed the number of injectable "
                "partition rule choices for this mode"
            )

        self.partition_rules = []
        if self.mode == "bi_part_groups":
            for _ in range(self.init_num_rules):
                self.partition_rules.append(
                    self._build_partition_rule(
                        partition=self._sample_partition_groups(),
                        partition_seq=self.partition_seq,
                        partition_duration=self.partition_duration,
                    )
                )
        elif self.mode == "flex_bi_part_groups":
            selected_seqs = random.sample(
                range(self.byzz_min_seq, self.byzz_max_seq + 1),
                self.init_num_rules,
            )
            for seq in selected_seqs:
                self.partition_rules.append(
                    self._build_partition_rule(
                        partition=self._sample_partition_groups(),
                        partition_seq=seq,
                        partition_duration=random.randint(1, self.max_partition_duration),
                    )
                )
        elif self.mode == "flex_msg_part_groups":
            choices = [
                (seq, message_type.__name__)
                for seq in range(self.byzz_min_seq, self.byzz_max_seq + 1)
                for message_type in self._message_types.values()
            ]
            for seq, message_type in random.sample(choices, self.init_num_rules):
                self.partition_rules.append(
                    self._build_partition_rule(
                        partition=self._sample_partition_groups(),
                        partition_seq=seq,
                        start_after_ms=random.randint(
                            0, self.max_partition_start_after_ms
                        ),
                        message_type=message_type,
                    )
                )
        elif self.mode == OPEN_LATE_PART_GROUPS:
            selected_seqs = random.sample(
                range(self.byzz_min_seq, self.byzz_max_seq + 1),
                self.init_num_rules,
            )
            for seq in selected_seqs:
                self.partition_rules.append(
                    self._build_partition_rule(
                        partition=self._sample_partition_groups(),
                        partition_seq=seq,
                        start_after_ms=random.randint(
                            0, self.max_partition_start_after_ms
                        ),
                    )
                )
        else:
            raise ValueError(f"Invalid partition mode: {self.mode}")

        for rule in self.partition_rules:
            self._repair_partition_rule(rule)
        self._sync_legacy_partition_fields()

    def _max_partition_rule_choices(self):
        num_seqs = self.byzz_max_seq - self.byzz_min_seq + 1
        if self.mode == "flex_msg_part_groups":
            return num_seqs * len(self._message_types)
        return num_seqs

    def _mutate_partition_assignment(self, rule):
        flip_idx = random.randint(0, len(rule["partition"]) - 1)
        rule["partition"][flip_idx] = 1 - rule["partition"][flip_idx]

    def mutate_self(self, force=False):
        if self.mode not in [
            "bi_part_groups",
            "flex_bi_part_groups",
            "flex_msg_part_groups",
            OPEN_LATE_PART_GROUPS,
        ]:
            return
        if not self.partition_rules:
            return

        rule = random.choice(self.partition_rules)
        if self.mode == "bi_part_groups":
            self._mutate_partition_assignment(rule)
            self._repair_partition_rule(rule)
            self._sync_legacy_partition_fields()
            return

        ops = ["partition"]
        if self.byzz_min_seq < self.byzz_max_seq:
            ops.append("seq")
        if self.mode == "flex_bi_part_groups" and self.max_partition_duration > 1:
            ops.append("duration")
        if self.mode in ["flex_msg_part_groups", OPEN_LATE_PART_GROUPS]:
            if self.max_partition_start_after_ms > 0:
                ops.append("start_after")
        if self.mode == "flex_msg_part_groups":
            if len(self._message_types) > 1:
                ops.append("message_type")

        op = random.choice(ops)
        if op == "partition":
            self._mutate_partition_assignment(rule)
        elif op == "seq":
            rule["partition_seq"] = self._random_int_excluding(
                self.byzz_min_seq,
                self.byzz_max_seq,
                rule["partition_seq"],
            )
        elif op == "duration":
            rule["partition_duration"] = self._random_int_excluding(
                1,
                self.max_partition_duration,
                rule["partition_duration"],
            )
        elif op == "start_after":
            rule["start_after_ms"] = self._random_int_excluding(
                0,
                self.max_partition_start_after_ms,
                rule.get("start_after_ms", 0),
            )
        elif op == "message_type":
            rule["message_type"] = self._random_partition_message_type(
                exclude=rule.get("message_type")
            )
        self._repair_partition_rule(rule)
        self._sync_legacy_partition_fields()

    def mate_with(self, other: "PartitionEncoding"):
        if self.mode != other.mode:
            raise ValueError(
                f"PartitionEncoding mode mismatch: self={self.mode}, other={other.mode}"
            )
        if self.mode not in [
            "bi_part_groups",
            "flex_bi_part_groups",
            "flex_msg_part_groups",
            OPEN_LATE_PART_GROUPS,
        ]:
            return
        if not self.partition_rules or not other.partition_rules:
            return
        if len(self.partition_rules) != len(other.partition_rules):
            raise ValueError(
                "PartitionEncoding crossover requires the same number of partition rules"
            )

        new_rules_self = []
        new_rules_other = []
        for left_rule, right_rule in zip(self.partition_rules, other.partition_rules):
            left_seq = int(left_rule["partition_seq"])
            right_seq = int(right_rule["partition_seq"])
            left_partition = list(left_rule["partition"])
            right_partition = list(right_rule["partition"])

            if random.random() < 0.5:
                left_seq, right_seq = right_seq, left_seq

            if self.mode in ["flex_msg_part_groups", OPEN_LATE_PART_GROUPS]:
                left_start_after = int(left_rule.get("start_after_ms", 0))
                right_start_after = int(right_rule.get("start_after_ms", 0))
                if random.random() < 0.5:
                    left_start_after, right_start_after = (
                        right_start_after,
                        left_start_after,
                    )
            if self.mode == "flex_msg_part_groups":
                left_message_type = left_rule.get("message_type")
                right_message_type = right_rule.get("message_type")
                if random.random() < 0.5:
                    left_message_type, right_message_type = (
                        right_message_type,
                        left_message_type,
                    )
            elif self.mode in ["bi_part_groups", "flex_bi_part_groups"]:
                left_duration = int(left_rule["partition_duration"])
                right_duration = int(right_rule["partition_duration"])
                if random.random() < 0.5:
                    left_duration, right_duration = right_duration, left_duration

            child_partition_left = list(left_partition)
            child_partition_right = list(right_partition)
            for idx, (left_value, right_value) in enumerate(
                zip(left_partition, right_partition)
            ):
                if left_value != right_value and random.random() < 0.5:
                    child_partition_left[idx], child_partition_right[idx] = (
                        child_partition_right[idx],
                        child_partition_left[idx],
                    )

            if self.mode == "flex_msg_part_groups":
                child_rule_left = self._build_partition_rule(
                    partition=child_partition_left,
                    partition_seq=left_seq,
                    start_after_ms=left_start_after,
                    message_type=left_message_type,
                )
                child_rule_right = self._build_partition_rule(
                    partition=child_partition_right,
                    partition_seq=right_seq,
                    start_after_ms=right_start_after,
                    message_type=right_message_type,
                )
            elif self.mode == OPEN_LATE_PART_GROUPS:
                child_rule_left = self._build_partition_rule(
                    partition=child_partition_left,
                    partition_seq=left_seq,
                    start_after_ms=left_start_after,
                )
                child_rule_right = self._build_partition_rule(
                    partition=child_partition_right,
                    partition_seq=right_seq,
                    start_after_ms=right_start_after,
                )
            else:
                child_rule_left = self._build_partition_rule(
                    partition=child_partition_left,
                    partition_seq=left_seq,
                    partition_duration=left_duration,
                )
                child_rule_right = self._build_partition_rule(
                    partition=child_partition_right,
                    partition_seq=right_seq,
                    partition_duration=right_duration,
                )
            self._repair_partition_rule(child_rule_left)
            other._repair_partition_rule(child_rule_right)
            new_rules_self.append(child_rule_left)
            new_rules_other.append(child_rule_right)

        self.partition_rules = new_rules_self
        other.partition_rules = new_rules_other
        self._sync_legacy_partition_fields()
        other._sync_legacy_partition_fields()

    def to_dict(self):
        res = {
            "mode": self.mode,
            "start_partition": self.start_partition,
            "partition_seq": self.partition_seq,
            "partition_duration": self.partition_duration,
        }
        if self.mode == "flex_bi_part_groups":
            res["max_partition_duration"] = self.max_partition_duration
        if self.mode in ["flex_msg_part_groups", OPEN_LATE_PART_GROUPS]:
            res["max_partition_start_after_ms"] = self.max_partition_start_after_ms
        if self.partition_rules:
            rules = []
            for rule in self.partition_rules:
                rule_dict = {
                    "partition_seq": int(rule["partition_seq"]),
                    "partition": list(rule["partition"]),
                }
                if self.mode == "flex_msg_part_groups":
                    rule_dict["start_after_ms"] = int(rule["start_after_ms"])
                    rule_dict["message_type"] = str(rule["message_type"])
                elif self.mode == OPEN_LATE_PART_GROUPS:
                    rule_dict["start_after_ms"] = int(rule["start_after_ms"])
                else:
                    rule_dict["partition_duration"] = int(rule["partition_duration"])
                rules.append(rule_dict)
            res["partition_rules"] = rules
        if self.partition is not None:
            res["partition"] = list(self.partition)
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
        SPARSE_SET_RULES,  # (seq, from_nodes, to_nodes, message_type) -> delay
        SPARSE_SEQ_PROPOSAL_RULES,  # (seq, pro_seq, from, to, message_type) -> delay
        # (seq, pro_seq, from_nodes, to_nodes, message_type) -> delay
        SPARSE_SEQ_PROPOSAL_SET_RULES,
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
        max_proposal_seq=5,
    ):
        if mode not in self.delay_modes:
            raise ValueError(f"Invalid delay mode: {mode}")

        self.num_nodes = num_nodes
        self.delay_min = delay_min
        self.delay_max = delay_max
        self.byzz_min_seq = byzz_min_seq
        self.byzz_max_seq = byzz_max_seq
        self.init_num_rules = init_num_rules
        self.max_proposal_seq = int(max_proposal_seq)
        if self.max_proposal_seq < 0:
            raise ValueError("max_proposal_seq must be non-negative")

        self.mode = mode
        self.delay_constraints = None
        self._sample_dealy_rules()

    @staticmethod
    def _random_subset(candidates):
        if not candidates:
            return tuple()
        size = random.randint(1, len(candidates))
        return tuple(sorted(random.sample(candidates, size)))

    def _repair_delay_node_sets(self, from_nodes, to_nodes):
        all_nodes = set(range(self.num_nodes))
        from_set = {int(node) for node in from_nodes if int(node) in all_nodes}
        to_set = {int(node) for node in to_nodes if int(node) in all_nodes}

        if not from_set:
            from_set.add(random.randrange(self.num_nodes))
        to_set -= from_set
        if not to_set:
            candidates = sorted(all_nodes - from_set)
            if candidates:
                to_set.add(random.choice(candidates))
            elif self.num_nodes > 1:
                # If from_set covers every node, shrink it so a non-empty,
                # disjoint receiver set can exist.
                moved = random.choice(sorted(from_set))
                from_set.remove(moved)
                to_set.add(moved)

        if not from_set or not to_set:
            raise ValueError("delay set rules require at least two nodes")
        return tuple(sorted(from_set)), tuple(sorted(to_set))

    def _random_delay_node_sets(self):
        if self.num_nodes < 2:
            raise ValueError("delay set rules require at least two nodes")
        nodes = list(range(self.num_nodes))
        from_nodes = set(self._random_subset(nodes))
        to_candidates = [node for node in nodes if node not in from_nodes]
        if not to_candidates:
            moved = random.choice(sorted(from_nodes))
            from_nodes.remove(moved)
            to_candidates = [moved]
        to_nodes = set(self._random_subset(to_candidates))
        return self._repair_delay_node_sets(from_nodes, to_nodes)

    def _random_sparse_delay_key(self):
        seq = random.randint(self.byzz_min_seq, self.byzz_max_seq)
        message_type = random.choice(list(MESSAGE_TYPE_MAP.values())).__name__
        if self.mode == "sparse_rules":
            from_node = random.randrange(self.num_nodes)
            to_node = random.randrange(self.num_nodes - 1)
            if to_node >= from_node:
                to_node += 1
            return (seq, from_node, to_node, message_type)
        if self.mode == SPARSE_SEQ_PROPOSAL_RULES:
            from_node = random.randrange(self.num_nodes)
            to_node = random.randrange(self.num_nodes - 1)
            if to_node >= from_node:
                to_node += 1
            pro_seq = random.randint(OPEN_PROPOSAL_SEQ, self.max_proposal_seq)
            return (seq, pro_seq, from_node, to_node, message_type)
        if self.mode == SPARSE_SET_RULES:
            from_nodes, to_nodes = self._random_delay_node_sets()
            return (seq, from_nodes, to_nodes, message_type)
        if self.mode == SPARSE_SEQ_PROPOSAL_SET_RULES:
            from_nodes, to_nodes = self._random_delay_node_sets()
            pro_seq = random.randint(OPEN_PROPOSAL_SEQ, self.max_proposal_seq)
            return (seq, pro_seq, from_nodes, to_nodes, message_type)
        return None

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
        elif self.mode in [
            "sparse_rules",
            SPARSE_SET_RULES,
            SPARSE_SEQ_PROPOSAL_RULES,
            SPARSE_SEQ_PROPOSAL_SET_RULES,
        ]:
            self.delay_constraints = {}
            self.add_random_sparse_delay_rules(to_add=self.init_num_rules)
        else:
            raise ValueError(f"Invalid delay mode: {self.mode}")

    def add_random_sparse_delay_rules(self, to_add=1):
        if self.mode not in [
            "sparse_rules",
            SPARSE_SET_RULES,
            SPARSE_SEQ_PROPOSAL_RULES,
            SPARSE_SEQ_PROPOSAL_SET_RULES,
        ]:
            return
        if self.delay_constraints is None:
            self.delay_constraints = {}
        if self.mode == "sparse_rules":
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
        elif self.mode == SPARSE_SEQ_PROPOSAL_RULES:
            choices = [
                (seq, pro_seq, from_node, to_node, message_type.__name__)
                for seq in range(self.byzz_min_seq, self.byzz_max_seq + 1)
                for pro_seq in range(OPEN_PROPOSAL_SEQ, self.max_proposal_seq + 1)
                for from_node in range(self.num_nodes)
                for to_node in range(self.num_nodes)
                if from_node != to_node
                for message_type in MESSAGE_TYPE_MAP.values()
                if (seq, pro_seq, from_node, to_node, message_type.__name__)
                not in self.delay_constraints
            ]
        elif self.mode in [SPARSE_SET_RULES, SPARSE_SEQ_PROPOSAL_SET_RULES]:
            choices = []
            attempts = 0
            max_attempts = max(100, to_add * 50)
            while len(choices) < to_add and attempts < max_attempts:
                attempts += 1
                key = self._random_sparse_delay_key()
                if (
                    key is None
                    or key in self.delay_constraints
                    or key in choices
                ):
                    continue
                choices.append(key)
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

    def _mutate_sparse_set_rules(self):
        if self.delay_constraints is None:
            self.delay_constraints = {}

        op = random.choice(["modify", "add", "delete"])

        if op == "modify":
            if not self.delay_constraints:
                self.add_random_sparse_delay_rules(to_add=1)
                return
            key = random.choice(list(self.delay_constraints.keys()))
            delay = self.delay_constraints.pop(key)
            has_pro_seq = len(key) == 5
            if has_pro_seq:
                seq, pro_seq, from_nodes, to_nodes, message_type = key
                fields = [
                    "delay",
                    "seq",
                    "pro_seq",
                    "from_nodes",
                    "to_nodes",
                    "message_type",
                ]
            else:
                seq, from_nodes, to_nodes, message_type = key
                pro_seq = None
                fields = ["delay", "seq", "from_nodes", "to_nodes", "message_type"]
            field = random.choice(fields)
            if field == "delay":
                delay = self._random_delay(exclude=delay)
            elif field == "seq":
                seq = random.randint(self.byzz_min_seq, self.byzz_max_seq)
            elif field == "pro_seq":
                pro_seq = random.randint(OPEN_PROPOSAL_SEQ, self.max_proposal_seq)
            elif field == "from_nodes":
                from_nodes = set(from_nodes)
                if random.random() < 0.5 and len(from_nodes) > 1:
                    from_nodes.remove(random.choice(sorted(from_nodes)))
                else:
                    candidates = [
                        node
                        for node in range(self.num_nodes)
                        if node not in from_nodes and node not in set(to_nodes)
                    ]
                    if candidates:
                        from_nodes.add(random.choice(candidates))
                    elif from_nodes:
                        from_nodes.remove(random.choice(sorted(from_nodes)))
                from_nodes, to_nodes = self._repair_delay_node_sets(from_nodes, to_nodes)
            elif field == "to_nodes":
                to_nodes = set(to_nodes)
                if random.random() < 0.5 and len(to_nodes) > 1:
                    to_nodes.remove(random.choice(sorted(to_nodes)))
                else:
                    candidates = [
                        node
                        for node in range(self.num_nodes)
                        if node not in to_nodes and node not in set(from_nodes)
                    ]
                    if candidates:
                        to_nodes.add(random.choice(candidates))
                    elif to_nodes:
                        to_nodes.remove(random.choice(sorted(to_nodes)))
                from_nodes, to_nodes = self._repair_delay_node_sets(from_nodes, to_nodes)
            elif field == "message_type":
                candidates = [
                    msg_type.__name__
                    for msg_type in MESSAGE_TYPE_MAP.values()
                    if msg_type.__name__ != message_type
                ]
                if candidates:
                    message_type = random.choice(candidates)
            if has_pro_seq:
                new_key = (seq, pro_seq, from_nodes, to_nodes, message_type)
            else:
                new_key = (seq, from_nodes, to_nodes, message_type)
            self.delay_constraints[new_key] = delay
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
        elif self.mode in ["sparse_rules", SPARSE_SEQ_PROPOSAL_RULES]:
            self._mutate_sparse_rules()
        elif self.mode in [SPARSE_SET_RULES, SPARSE_SEQ_PROPOSAL_SET_RULES]:
            self._mutate_sparse_set_rules()
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

    def _mate_sparse_set_rules(self, other):
        child1 = dict(self.delay_constraints or {})
        child2 = dict(other.delay_constraints or {})

        if child1 and child2:
            key1 = random.choice(list(child1.keys()))
            key2 = random.choice(list(child2.keys()))
            delay1 = child1.pop(key1)
            delay2 = child2.pop(key2)
            child_key1, child_delay1, child_key2, child_delay2 = (
                self._crossover_sparse_set_rule(key1, delay1, key2, delay2)
            )
            child1[child_key1] = child_delay1
            child2[child_key2] = child_delay2

        self.delay_constraints = child1
        other.delay_constraints = child2

    def _crossover_sparse_set_rule(self, key1, delay1, key2, delay2):
        has_pro_seq = len(key1) == 5
        if has_pro_seq != (len(key2) == 5):
            raise ValueError("Sparse set delay rule key shapes must match for crossover")
        if has_pro_seq:
            seq1, pro_seq1, from1, to1, msg1 = key1
            seq2, pro_seq2, from2, to2, msg2 = key2
        else:
            seq1, from1, to1, msg1 = key1
            seq2, from2, to2, msg2 = key2
            pro_seq1 = None
            pro_seq2 = None

        if random.random() < 0.5:
            seq1, seq2 = seq2, seq1
        if has_pro_seq and random.random() < 0.5:
            pro_seq1, pro_seq2 = pro_seq2, pro_seq1
        if random.random() < 0.5:
            msg1, msg2 = msg2, msg1
        if random.random() < 0.5:
            delay1, delay2 = delay2, delay1

        from1, from2 = self._crossover_node_sets(from1, from2)
        to1, to2 = self._crossover_node_sets(to1, to2)
        from1, to1 = self._repair_delay_node_sets(from1, to1)
        from2, to2 = self._repair_delay_node_sets(from2, to2)

        if not has_pro_seq:
            return (
                (seq1, from1, to1, msg1),
                delay1,
                (seq2, from2, to2, msg2),
                delay2,
            )
        return (
            (seq1, pro_seq1, from1, to1, msg1),
            delay1,
            (seq2, pro_seq2, from2, to2, msg2),
            delay2,
        )

    def _crossover_node_sets(self, left_nodes, right_nodes):
        left = set(left_nodes)
        right = set(right_nodes)
        child_left = set(left)
        child_right = set(right)
        for node in range(self.num_nodes):
            if (node in left) != (node in right) and random.random() < 0.5:
                if node in child_left:
                    child_left.remove(node)
                    child_right.add(node)
                else:
                    child_left.add(node)
                    child_right.discard(node)
        if not child_left:
            child_left.add(random.randrange(self.num_nodes))
        if not child_right:
            child_right.add(random.randrange(self.num_nodes))
        return tuple(sorted(child_left)), tuple(sorted(child_right))

    def mate_with(self, other):
        if self.mode != other.mode:
            raise ValueError(
                f"DelayEncoding mode mismatch: self={self.mode}, other={other.mode}"
            )
        if self.mode in ["none", "random"]:
            return
        if self.mode in ["dense_rules", "dense_seq_rules"]:
            self._mate_dense_mapping(other)
        elif self.mode in ["sparse_rules", SPARSE_SEQ_PROPOSAL_RULES]:
            self._mate_sparse_rules(other)
        elif self.mode in [SPARSE_SET_RULES, SPARSE_SEQ_PROPOSAL_SET_RULES]:
            self._mate_sparse_set_rules(other)
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
            elif self.mode == SPARSE_SEQ_PROPOSAL_RULES:
                res["delays"] = [
                    {
                        "seq": seq,
                        "pro_seq": pro_seq,
                        "from_node": from_node,
                        "to_node": to_node,
                        "message_type": message_type,
                        "delay": delay,
                    }
                    for (
                        seq,
                        pro_seq,
                        from_node,
                        to_node,
                        message_type,
                    ), delay in self.delay_constraints.items()
                ]
            elif self.mode == SPARSE_SET_RULES:
                res["delays"] = [
                    {
                        "seq": seq,
                        "from_nodes": list(from_nodes),
                        "to_nodes": list(to_nodes),
                        "message_type": message_type,
                        "delay": delay,
                    }
                    for (
                        seq,
                        from_nodes,
                        to_nodes,
                        message_type,
                    ), delay in self.delay_constraints.items()
                ]
            elif self.mode == SPARSE_SEQ_PROPOSAL_SET_RULES:
                res["delays"] = [
                    {
                        "seq": seq,
                        "pro_seq": pro_seq,
                        "from_nodes": list(from_nodes),
                        "to_nodes": list(to_nodes),
                        "message_type": message_type,
                        "delay": delay,
                    }
                    for (
                        seq,
                        pro_seq,
                        from_nodes,
                        to_nodes,
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
            if isinstance(from_node, tuple) or isinstance(to_node, tuple):
                return (
                    f"seq={seq}, from_nodes={list(from_node)}, "
                    f"to_nodes={list(to_node)}, "
                    f"message_type={cls._format_message_type(message_type)}"
                )
            return (
                f"seq={seq}, from_node={from_node}, to_node={to_node}, "
                f"message_type={cls._format_message_type(message_type)}"
            )
        if len(key) == 5:
            seq, pro_seq, from_node, to_node, message_type = key
            if isinstance(from_node, tuple) or isinstance(to_node, tuple):
                return (
                    f"seq={seq}, pro_seq={pro_seq}, from_nodes={list(from_node)}, "
                    f"to_nodes={list(to_node)}, "
                    f"message_type={cls._format_message_type(message_type)}"
                )
            return (
                f"seq={seq}, pro_seq={pro_seq}, from_node={from_node}, "
                f"to_node={to_node}, "
                f"message_type={cls._format_message_type(message_type)}"
            )
        return str(key)

    @classmethod
    def _format_byzz_key(cls, key):
        if len(key) == 3:
            seq, to_node, message_type = key
            if isinstance(to_node, tuple):
                return (
                    f"seq={seq}, to_nodes={list(to_node)}, "
                    f"message_type={cls._format_message_type(message_type)}"
                )
            return (
                f"seq={seq}, to_node={to_node}, "
                f"message_type={cls._format_message_type(message_type)}"
            )
        if len(key) == 4:
            seq, pro_seq, to_node, message_type = key
            if isinstance(to_node, tuple):
                return (
                    f"seq={seq}, pro_seq={pro_seq}, to_nodes={list(to_node)}, "
                    f"message_type={cls._format_message_type(message_type)}"
                )
            return (
                f"seq={seq}, pro_seq={pro_seq}, to_node={to_node}, "
                f"message_type={cls._format_message_type(message_type)}"
            )
        return str(key)

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

        lines = []
        if (
            self.partition_encoding.start_partition
            != other.partition_encoding.start_partition
        ):
            lines.append(
                "PartitionEncoding: "
                f"start_partition {other.partition_encoding.start_partition} -> "
                f"{self.partition_encoding.start_partition}"
            )
        current_rules = self.partition_encoding.partition_rules or []
        previous_rules = other.partition_encoding.partition_rules or []

        if len(current_rules) != len(previous_rules):
            lines.append(
                "PartitionEncoding: "
                f"rule_count {len(previous_rules)} -> {len(current_rules)}"
            )

        for idx in range(max(len(current_rules), len(previous_rules))):
            if idx >= len(previous_rules):
                lines.append(f"PartitionEncoding rule[{idx}] added: {current_rules[idx]}")
                continue
            if idx >= len(current_rules):
                lines.append(
                    f"PartitionEncoding rule[{idx}] removed: {previous_rules[idx]}"
                )
                continue

            current_rule = current_rules[idx]
            previous_rule = previous_rules[idx]
            if current_rule["partition_seq"] != previous_rule["partition_seq"]:
                lines.append(
                    "PartitionEncoding: "
                    f"rule[{idx}].partition_seq {previous_rule['partition_seq']} -> "
                    f"{current_rule['partition_seq']}"
                )
            if current_rule.get("partition_duration") != previous_rule.get(
                "partition_duration"
            ):
                lines.append(
                    "PartitionEncoding: "
                    f"rule[{idx}].partition_duration "
                    f"{previous_rule.get('partition_duration')} -> "
                    f"{current_rule.get('partition_duration')}"
                )
            if current_rule.get("start_after_ms") != previous_rule.get(
                "start_after_ms"
            ):
                lines.append(
                    "PartitionEncoding: "
                    f"rule[{idx}].start_after_ms "
                    f"{previous_rule.get('start_after_ms')} -> "
                    f"{current_rule.get('start_after_ms')}"
                )
            if current_rule.get("message_type") != previous_rule.get("message_type"):
                lines.append(
                    "PartitionEncoding: "
                    f"rule[{idx}].message_type "
                    f"{previous_rule.get('message_type')} -> "
                    f"{current_rule.get('message_type')}"
                )

            changed = [
                (node_idx, old_value, new_value)
                for node_idx, (old_value, new_value) in enumerate(
                    zip(previous_rule["partition"], current_rule["partition"])
                )
                if old_value != new_value
            ]
            if changed:
                lines.append(
                    f"PartitionEncoding: rule[{idx}] {len(changed)} node(s) changed"
                )
                for node_idx, old_value, new_value in changed:
                    lines.append(f"  node {node_idx}: {old_value} -> {new_value}")
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

        def normalize_byzz_rule(rule):
            if len(rule) == 4:
                seq, to_node, message_type, method = rule
                if isinstance(to_node, tuple):
                    to_node = tuple(int(node) for node in to_node)
                key = (seq, to_node, self._format_message_type(message_type))
            elif len(rule) == 5:
                seq, pro_seq, to_node, message_type, method = rule
                if isinstance(to_node, tuple):
                    to_node = tuple(int(node) for node in to_node)
                key = (
                    seq,
                    pro_seq,
                    to_node,
                    self._format_message_type(message_type),
                )
            else:
                raise ValueError(f"Invalid byzz rule format: {rule}")
            return key, method

        current = dict(normalize_byzz_rule(rule) for rule in current_rules)
        previous = dict(normalize_byzz_rule(rule) for rule in previous_rules)

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
            max_proposal_seq=configs.get("max_proposal_seq", 5),
            byzz_enabled_mutation_methods=configs.get(
                "byzz_enabled_mutation_methods"
            ),
            byzz_disabled_mutation_methods=configs.get(
                "byzz_disabled_mutation_methods"
            ),
        )

        delay_encoding = DelayEncoding(
            mode=configs["delay_mode"],
            num_nodes=configs["number_of_nodes"],
            delay_min=configs["min_delay_ms"],
            delay_max=configs["max_delay_ms"],
            byzz_min_seq=configs["byzz_min_seq"],
            byzz_max_seq=configs["byzz_max_seq"],
            init_num_rules=configs.get("delay_init_num_rules", 5),
            max_proposal_seq=configs.get("max_proposal_seq", 5),
        )

        partition_encoding = PartitionEncoding(
            mode=configs["partition_mode"],
            num_nodes=configs["number_of_nodes"],
            partition_seq=configs.get("partition_seq", 5),
            partition_duration=configs.get(
                "partition_duration",
                configs.get("max_partition_duration", 1000),
            ),
            byzz_min_seq=configs["byzz_min_seq"],
            byzz_max_seq=configs["byzz_max_seq"],
            max_partition_duration=configs.get("max_partition_duration", 1000),
            max_partition_start_after_ms=configs.get(
                "max_partition_start_after_ms",
                configs.get("max_partition_duration", 1000),
            ),
            start_partition=configs.get("start_partition", "open"),
            init_num_rules=configs.get("partition_init_num_rules", 1),
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


def _demo_configs(delay_mode="sparse_rules", partition_mode="bi_part_groups", byzz_mode="sparse_rules"):
    return {
        "byzz_mode": byzz_mode,
        "delay_mode": delay_mode,
        "partition_mode": partition_mode,
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
        "timeout_sec_per_seq": 30,
    }


def _build_strategy_input_payload(encoding_dict, configs, seed=42):
    return {
        "seed": seed,
        "encoding": encoding_dict,
        "byzz_min_seq": configs["byzz_min_seq"],
        "byzz_max_seq": configs["byzz_max_seq"],
        "min_delay_ms": configs["min_delay_ms"],
        "max_delay_ms": configs["max_delay_ms"],
        "timeout_sec_per_seq": configs["timeout_sec_per_seq"],
        "seqcheck": configs.get("seqcheck", "statuschange"),
    }


def _write_yaml(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


if __name__ == "__main__":
    configs = _demo_configs()
    output_root = Path(__file__).resolve().parent / "tmp" / "composeencoding_samples"
    strategy_input_dir = output_root / "strategy_input"

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

    for delay_mode in DelayEncoding.delay_modes:
        for partition_mode in PartitionEncoding.partition_modes:
            for byzz_mode in ByzzEncoding.byzz_modes:
                combo_configs = _demo_configs(
                    delay_mode=delay_mode,
                    partition_mode=partition_mode,
                    byzz_mode=byzz_mode,
                )
                compose = ComposeEncoding.sample(combo_configs)
                payload = _build_strategy_input_payload(
                    compose.to_dict(), combo_configs
                )
                filename = (
                    f"strategy_input__delay-{delay_mode}"
                    f"__partition-{partition_mode}"
                    f"__byzz-{byzz_mode}.yaml"
                )
                _write_yaml(strategy_input_dir / filename, payload)

    print(f"Generated encoding sample YAML files under: {output_root}")
