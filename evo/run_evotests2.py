#!/usr/bin/env python3
"""Run evo tests with config runner threads and one shared evaluation pool.

This is a compatibility-oriented replacement for ``run_evotests.py`` +
``evotest_parallel.py``.  It still reads ``evo/run_evotests.yaml`` and expands
the same image / strategy-mode / fitness combinations, but all individual
evaluations are submitted to one global ``ProcessPoolExecutor``.
"""

from __future__ import annotations

import copy
import os
import queue
import random
import re
import signal
import sys
import threading
import time
import traceback
from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from deap import algorithms, base, creator, tools


THIS_FILE = Path(__file__).resolve()
EVO_DIR = THIS_FILE.parent
REPO_ROOT = EVO_DIR.parent

for path in (str(REPO_ROOT), str(EVO_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from evo import encoding
from evologger import EvoLogger
from run_rocket import INVALID_RUNTIME_FITNESS, run_rocket_and_evaluate
from utils import (
    get_date_time_strf,
    get_dirs,
    get_strategy_name,
    make_cluster_id,
    setup_docker_images,
)


DEFAULT_EVOTEST_CONFIG: dict[str, Any] = {
    "seed": 98,
    "min_delay_ms": 0,
    "max_delay_ms": 100,
    "rust_log_level": "info",
    "byzz_min_seq": 5,
    "byzz_max_seq": 10,
    "seqcheck": "statuschange",
    "max_ledger_seq": 15,
    "total_num_tests": 500,
    "population_size": 10,
    "strategy": "ComposedStrategy",
    "max_parallel_workers": 1,
    "base_network_config_yaml": "network.yaml",
    "mu": 4,
    "timeout_per_seq": 30,
    "individual_timeout_sec": None,
    "runtime_retries": 1,
    "logs_group_dir": None,
    "output_screen": False,
    "partition_seq": 5,
    "partition_duration": None,
    "max_partition_duration": 1000,
    "start_partition": "open",
    "delay_mode": None,
    "partition_mode": None,
    "byzz_mode": None,
    "force_exit_on_second_sigint": False,
}


_deap_setup_lock = threading.Lock()
_print_lock = threading.Lock()
_active_pool: "SharedEvaluationPool | None" = None
_main_stop_event: threading.Event | None = None
_signal_count = 0
_force_exit_on_second_sigint = False


@dataclass(frozen=True)
class EvaluationTask:
    experiment_id: str
    generation: int
    individual_id: int
    genes: dict[str, Any]
    config: dict[str, Any]


@dataclass
class RunnerSummary:
    experiment_id: str
    label: str
    status: str
    evaluations: int
    elapsed_sec: float
    best_fitness: float | None = None
    best_log_dir: str | None = None


def log_line(message: str):
    with _print_lock:
        print(message, flush=True)


def normalize_strategy_combo(entry) -> dict[str, str]:
    """Normalize a strategy config entry into a composed-mode triple."""
    if isinstance(entry, dict):
        combo = {
            "delay_mode": entry.get("delay_mode"),
            "partition_mode": entry.get("partition_mode"),
            "byzz_mode": entry.get("byzz_mode"),
        }
    elif isinstance(entry, (list, tuple)) and len(entry) == 3:
        combo = {
            "delay_mode": entry[0],
            "partition_mode": entry[1],
            "byzz_mode": entry[2],
        }
    else:
        raise ValueError(
            "Each strategies entry must be either a dict with "
            "{delay_mode, partition_mode, byzz_mode} or a 3-item list/tuple."
        )

    missing = [key for key, value in combo.items() if not value]
    if missing:
        raise ValueError(f"Strategy mode combo is missing values for: {missing}")
    return combo


def format_strategy_combo(combo: dict[str, str]) -> str:
    return (
        f"delay-{combo['delay_mode']}__"
        f"partition-{combo['partition_mode']}__"
        f"byzz-{combo['byzz_mode']}"
    )


def is_pure_random_strategy_combo(combo: dict[str, str]) -> bool:
    return (
        combo.get("delay_mode") == "random"
        and combo.get("partition_mode") == "random_bipart"
        and combo.get("byzz_mode") == "random"
    )


def fitnesses_for_strategy_combo(
    combo: dict[str, str],
    configured_fitnesses: list[str],
) -> list[str]:
    if is_pure_random_strategy_combo(combo):
        return ["no_fitness"]
    return configured_fitnesses


def safe_path_part(value: str) -> str:
    return value.replace(":", "_").replace("/", "_")


def load_config(config_file: Path) -> dict[str, Any]:
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")
    with open(config_file, "r") as f:
        return yaml.safe_load(f) or {}


def validate_config(config: dict[str, Any]):
    required = ["ripple_images", "strategies", "fitness_functions"]
    missing = [key for key in required if not config.get(key)]
    if missing:
        raise ValueError(f"Missing required config keys: {missing}")

    for key in required:
        if not isinstance(config[key], list):
            raise ValueError(f"Config key '{key}' must be a list")

    for entry in config["strategies"]:
        normalize_strategy_combo(entry)

    positive_int_keys = [
        "max_parallel_workers",
        "max_concurrent_tasks",
        "max_config_threads",
        "individual_timeout_sec",
        "population_size",
        "total_num_tests",
        "mu",
        "partition_seq",
        "partition_duration",
        "max_partition_duration",
    ]
    for key in positive_int_keys:
        if key in config and config[key] is not None:
            if not isinstance(config[key], int) or config[key] <= 0:
                raise ValueError(f"Config key '{key}' must be a positive integer")

    if "runtime_retries" in config and config["runtime_retries"] is not None:
        if not isinstance(config["runtime_retries"], int) or config["runtime_retries"] < 0:
            raise ValueError("Config key 'runtime_retries' must be a non-negative integer")

    if config.get("start_partition") not in (None, "open", "establish"):
        raise ValueError("Config key 'start_partition' must be one of: open, establish")

    seqcheck = config.get("seqcheck")
    if seqcheck is not None and str(seqcheck).lower() not in ("fullyval", "statuschange"):
        raise ValueError("Config key 'seqcheck' must be one of: fullyval, statuschange")


def get_parallel_mode(config: dict[str, Any]) -> str:
    mode = str(config.get("parallel_mode", "parallel")).lower()
    if mode not in ("serial", "parallel"):
        log_line(f"Warning: invalid parallel_mode '{mode}', using 'parallel'")
        return "parallel"
    return mode


def get_max_concurrent_tasks(config: dict[str, Any]) -> int:
    value = config.get("max_concurrent_tasks", config.get("max_parallel_workers", 1))
    value = int(value or 1)
    if value <= 0:
        raise ValueError("max_concurrent_tasks must be positive")
    return value


def extend_run_config(
    base_config: dict[str, Any],
    dirs: dict[str, Path],
    *,
    experiment_id: str,
    ripple_image: str,
    strategy_combo: dict[str, str],
    fitness_function: str,
    logs_group_dir: Path,
) -> dict[str, Any]:
    config = copy.deepcopy(DEFAULT_EVOTEST_CONFIG)
    config.update(copy.deepcopy(base_config))
    config.update(dirs)

    config["experiment_id"] = experiment_id
    config["ripple_image"] = ripple_image
    config["strategy"] = "ComposedStrategy"
    config["delay_mode"] = strategy_combo["delay_mode"]
    config["partition_mode"] = strategy_combo["partition_mode"]
    config["byzz_mode"] = strategy_combo["byzz_mode"]
    config["fitness_function"] = fitness_function
    config["logs_group_dir"] = str(logs_group_dir)
    config["test_log_dir"] = logs_group_dir
    config["output_screen"] = bool(config.get("output_screen", False))

    network_yaml = Path(config["cur_dir"]) / config.get(
        "base_network_config_yaml", "network.yaml"
    )
    with open(network_yaml, "r") as f:
        network_config = yaml.safe_load(f)

    config["network_yaml"] = network_yaml
    config["base_network_config"] = network_config
    config["number_of_nodes"] = network_config.get("number_of_nodes")
    config["byzz_nodes"] = network_config.get("byzz_nodes")
    if config.get("max_partition_duration") is None:
        config["max_partition_duration"] = int(config.get("partition_duration") or 1000)
    else:
        config["max_partition_duration"] = int(config["max_partition_duration"])
    config["partition_seq"] = int(config.get("partition_seq") or 5)
    config["partition_duration"] = int(
        config.get("partition_duration") or config["max_partition_duration"]
    )
    config["start_partition"] = config.get("start_partition") or "open"
    config["seqcheck"] = str(config.get("seqcheck") or "statuschange").lower()

    population_size = int(config.get("population_size", 10))
    total_num_tests = int(config.get("total_num_tests", 500))
    config["max_generation"] = total_num_tests // population_size

    if config.get("individual_timeout_sec") is None:
        max_ledger_seq = int(config.get("max_ledger_seq", 15) or 15)
        timeout_per_seq = int(config.get("timeout_per_seq", 30) or 30)
        config["individual_timeout_sec"] = max_ledger_seq * timeout_per_seq * 2

    return config


def build_run_configs(
    config: dict[str, Any],
    dirs: dict[str, Path],
) -> tuple[list[dict[str, Any]], Path]:
    images = config["ripple_images"]
    strategies = [normalize_strategy_combo(entry) for entry in config["strategies"]]
    fitnesses = config["fitness_functions"]

    root_log_dir = Path(
        config.get("logs_group_root")
        or config.get("logs_group_dir")
        or (Path(dirs["logs_dir"]) / get_date_time_strf())
    )
    root_log_dir.mkdir(parents=True, exist_ok=True)

    run_configs: list[dict[str, Any]] = []
    idx = 0
    for strategy_combo in strategies:
        strategy_label = format_strategy_combo(strategy_combo)
        for fitness in fitnesses_for_strategy_combo(strategy_combo, fitnesses):
            for image in images:
                image_label = safe_path_part(image)
                experiment_id = f"E{idx:03d}_{image_label}__{strategy_label}__{fitness}"
                logs_group_dir = root_log_dir / image_label / strategy_label / fitness
                run_configs.append(
                    extend_run_config(
                        config,
                        dirs,
                        experiment_id=experiment_id,
                        ripple_image=image,
                        strategy_combo=strategy_combo,
                        fitness_function=fitness,
                        logs_group_dir=logs_group_dir,
                    )
                )
                idx += 1

    return run_configs, root_log_dir


def print_config_summary(
    config: dict[str, Any],
    run_configs: list[dict[str, Any]],
    root_log_dir: Path,
    max_concurrent_tasks: int,
    config_thread_limit: int,
):
    images = config["ripple_images"]
    strategies = [normalize_strategy_combo(entry) for entry in config["strategies"]]
    fitnesses = config["fitness_functions"]
    strategy_labels = [format_strategy_combo(combo) for combo in strategies]

    print()
    print("=" * 70)
    print("RUN_EVOTESTS2 CONFIGURATION SUMMARY")
    print("=" * 70)
    print(f"  Config file:              evo/run_evotests.yaml")
    print(f"  Root log dir:             {root_log_dir}")
    print(f"  Ripple images ({len(images)}):        {', '.join(images)}")
    print(f"  Mode combos ({len(strategies)}):        {', '.join(strategy_labels)}")
    print(f"  Fitness functions ({len(fitnesses)}):  {', '.join(fitnesses)}")
    if any(is_pure_random_strategy_combo(combo) for combo in strategies):
        print("  Pure random combos:       use no_fitness placeholder")
    print(f"  Total config runners:     {len(run_configs)}")
    print(f"  Config runner threads:    {config_thread_limit}")
    print(f"  Max concurrent tasks:     {max_concurrent_tasks} (global)")
    print(f"  Population size:          {config.get('population_size', 10)}")
    print(f"  Mu:                       {config.get('mu', 4)}")
    print(f"  Total num tests:          {config.get('total_num_tests', 500)}")
    print(f"  Start partition:          {config.get('start_partition', 'open')}")
    print(f"  Seq check:                {config.get('seqcheck', 'statuschange')}")
    print(f"  Max partition duration:   {config.get('max_partition_duration', 'default')}ms")
    print(f"  Individual timeout:       {config.get('individual_timeout_sec')}s")
    print(f"  Runtime retries:          {config.get('runtime_retries', 1)}")
    print("=" * 70)
    print()


def setup_deap_types():
    with _deap_setup_lock:
        if not hasattr(creator, "FitnessMax"):
            creator.create("FitnessMax", base.Fitness, weights=(1.0,))
        if not hasattr(creator, "Individual"):
            creator.create(
                "Individual",
                list,
                fitness=creator.FitnessMax,
                log_dir=None,
                evaluation_result=None,
            )


def use_composed_encoding(config: dict[str, Any]) -> bool:
    return all(
        config.get(key) is not None
        for key in ["delay_mode", "partition_mode", "byzz_mode"]
    )


def get_encoding_cls(config: dict[str, Any]):
    if use_composed_encoding(config):
        return encoding.ComposeEncoding
    cls_name = f"{config['strategy']}Encoding"
    return getattr(encoding, cls_name)


def sample_individual(config: dict[str, Any]):
    setup_deap_types()
    encoding_cls = get_encoding_cls(config)
    ind = encoding_cls.sample(config)
    ind.fitness = creator.FitnessMax()
    ind.log_dir = None
    ind.evaluation_result = None
    return ind


def archive_retry_log_dir(log_dir: Path, attempt_idx: int, reason: str | None):
    if not log_dir.exists():
        return None

    safe_reason = re.sub(r"[^A-Za-z0-9_.-]+", "_", reason or "runtime_invalid").strip("_")
    safe_reason = safe_reason[:80] or "runtime_invalid"
    archived_dir = log_dir.parent / f"{log_dir.name}__attempt{attempt_idx}_{safe_reason}"
    suffix = 1
    while archived_dir.exists():
        archived_dir = (
            log_dir.parent / f"{log_dir.name}__attempt{attempt_idx}_{safe_reason}_{suffix}"
        )
        suffix += 1

    log_dir.rename(archived_dir)
    return archived_dir


def worker_warmup() -> int:
    return os.getpid()


def evaluate_task_worker(task: EvaluationTask) -> dict[str, Any]:
    config = task.config
    ind_id = f"G{task.generation}T{task.individual_id}"
    test_log_dir = Path(config["test_log_dir"])
    full_log_dir = test_log_dir / ind_id
    cluster_id = make_cluster_id(str(config["logs_dir"]), str(test_log_dir), ind_id)
    runtime_retries = max(0, int(config.get("runtime_retries", 1) or 0))
    seed = random.SystemRandom().randrange(2**31)

    result = None
    attempts_used = 0
    for attempts_used in range(1, runtime_retries + 2):
        result = run_rocket_and_evaluate(
            log_dir=full_log_dir,
            cluster_id=cluster_id,
            max_ledger_seq=config.get("max_ledger_seq"),
            seed=seed,
            encoding=task.genes,
            rocket_dir=Path(config["rocket_dir"]),
            tmp_dir=Path(config["tmp_dir"]),
            byzz_min_seq=config.get("byzz_min_seq", 5),
            byzz_max_seq=config.get("byzz_max_seq", 10),
            output_screen=config.get("output_screen", False),
            timeout_sec_per_seq=config.get("timeout_per_seq", 65),
            network_yaml=Path(config["network_yaml"]),
            base_port_number=None,
            strategy_name=get_strategy_name(config.get("strategy", "")),
            min_delay_ms=config.get("min_delay_ms"),
            max_delay_ms=config.get("max_delay_ms"),
            ripple_image=config.get("ripple_image", ""),
            rust_log_level=config.get("rust_log_level", "info"),
            fitness_function=config.get("fitness_function"),
            seqcheck=config.get("seqcheck", "statuschange"),
            individual_timeout_sec=config.get("individual_timeout_sec", 300),
        )
        if not result.get("runtime_invalid", False):
            break

        reason = result.get("runtime_invalid_reason", "unknown")
        print(
            f"[{cluster_id}] Runtime-invalid attempt "
            f"{attempts_used}/{runtime_retries + 1}: {reason}",
            flush=True,
        )
        if attempts_used <= runtime_retries:
            archived_dir = archive_retry_log_dir(full_log_dir, attempts_used, reason)
            if archived_dir is not None:
                print(f"[{cluster_id}] Archived failed attempt logs to {archived_dir}", flush=True)

    assert result is not None
    fitness = result.get("fitness", 0.0)
    print(f"[{cluster_id}] Fitness: {fitness}", flush=True)

    return {
        "generation": task.generation,
        "individual_id": task.individual_id,
        "fitness": fitness,
        "eval_result": result.get("eval_result", {}),
        "log_dir": str(full_log_dir),
        "genes": task.genes,
        "run_status": result.get("run_status", "ok"),
        "runtime_invalid": result.get("runtime_invalid", False),
        "runtime_invalid_reason": result.get("runtime_invalid_reason"),
        "attempts_used": attempts_used,
        "retcode": result.get("retcode"),
    }


class SharedEvaluationPool:
    def __init__(self, max_workers: int):
        self.max_workers = max_workers
        self.executor = ProcessPoolExecutor(max_workers=max_workers)
        self._terminated = False
        self._lock = threading.Lock()

    def warm_up(self):
        futures = [self.executor.submit(worker_warmup) for _ in range(self.max_workers)]
        pids = sorted({future.result() for future in futures})
        log_line(f"[scheduler] Warmed up {len(pids)} evaluation worker process(es): {pids}")

    def submit(self, task: EvaluationTask) -> Future:
        return self.executor.submit(evaluate_task_worker, task)

    def force_terminate(self):
        with self._lock:
            if self._terminated:
                return
            self._terminated = True
            processes = getattr(self.executor, "_processes", {}) or {}
            for proc in processes.values():
                try:
                    if proc.is_alive():
                        proc.terminate()
                except Exception:
                    pass

    def shutdown(self, *, wait_for_workers: bool, cancel_futures: bool):
        self.executor.shutdown(wait=wait_for_workers, cancel_futures=cancel_futures)


class ExperimentRunner:
    def __init__(
        self,
        config: dict[str, Any],
        pool: SharedEvaluationPool,
        stop_event: threading.Event,
    ):
        self.config = config
        self.pool = pool
        self.stop_event = stop_event
        self.experiment_id = config["experiment_id"]
        self.label = (
            f"{config['ripple_image']} / "
            f"{format_strategy_combo(config)} / "
            f"{config['fitness_function']}"
        )

    def log(self, message: str):
        log_line(f"[{self.experiment_id}] {message}")

    def run(self) -> RunnerSummary:
        started_at = time.time()
        setup_deap_types()
        EvoLogger.init_log(self.config["test_log_dir"])

        lambda_ = int(self.config["population_size"])
        mu = min(lambda_, int(self.config["mu"]))
        max_generation = int(self.config["max_generation"])
        encoding_cls = get_encoding_cls(self.config)

        toolbox = base.Toolbox()
        toolbox.register("individual", sample_individual, self.config)
        toolbox.register("population", tools.initRepeat, list, toolbox.individual)
        toolbox.register("mate", encoding_cls.mate)
        toolbox.register("mutate", encoding_cls.mutate)
        toolbox.register("select", tools.selBest)

        stats = tools.Statistics(lambda ind: ind.fitness.values)
        stats.register("avg", np.mean)
        stats.register("std", np.std)
        stats.register("min", np.min)
        stats.register("max", np.max)

        hof = tools.HallOfFame(1)
        logbook = tools.Logbook()
        logbook.header = ["gen", "nevals"] + stats.fields

        self.log("Initialization (Generation 0)")
        population = toolbox.population(n=lambda_)

        evaluation_count = 0
        results = self.evaluate_population(population, generation=0)
        if self.stop_event.is_set():
            return self.summary("stopped", started_at, evaluation_count, hof)

        evaluation_count += len(results)
        self.apply_results(population, results, generation=0)
        hof.update(population)
        record = stats.compile(population)
        logbook.record(gen=0, nevals=len(population), **record)
        self.log(logbook.stream)

        population = toolbox.select(population, mu)

        for gen in range(1, max_generation + 1):
            if self.stop_event.is_set():
                self.log("Stop requested. Exiting evolution loop.")
                break

            self.log(f"Generation {gen}")
            offspring = algorithms.varOr(
                population,
                toolbox,
                lambda_,
                cxpb=0.7,
                mutpb=0.3,
            )
            invalid_ind = [ind for ind in offspring if not ind.fitness.valid]

            if invalid_ind:
                results = self.evaluate_population(invalid_ind, generation=gen)
                if self.stop_event.is_set():
                    self.log("Stop requested during offspring evaluation.")
                    break
                evaluation_count += len(results)
                self.apply_results(invalid_ind, results, generation=gen)

            population = toolbox.select(population + offspring, mu)
            hof.update(population)
            record = stats.compile(population)
            logbook.record(gen=gen, nevals=len(invalid_ind), **record)
            self.log(logbook.stream)

        self.log("Evolution complete")
        if len(hof) > 0:
            best_ind = hof[0]
            best_fit = best_ind.fitness.values[0]
            best_log_dir = getattr(best_ind, "log_dir", None)
            self.log(f"Best fitness: {best_fit}")
            self.log(f"Best log dir: {best_log_dir}")
            if hasattr(best_ind, "to_dict"):
                self.log("Best encoding:\n" + yaml.safe_dump(best_ind.to_dict(), sort_keys=False).rstrip())

        return self.summary("ok", started_at, evaluation_count, hof)

    def evaluate_population(self, individuals: list[Any], generation: int) -> list[dict[str, Any]]:
        self.log(
            f"Submitting generation {generation} with {len(individuals)} individual(s) "
            f"to the shared pool"
        )
        futures: dict[Future, EvaluationTask] = {}
        for idx, ind in enumerate(individuals, start=1):
            if self.stop_event.is_set():
                break
            genes = ind.to_dict() if hasattr(ind, "to_dict") else list(ind)
            task = EvaluationTask(
                experiment_id=self.experiment_id,
                generation=generation,
                individual_id=idx,
                genes=genes,
                config=self.config,
            )
            futures[self.pool.submit(task)] = task

        results: list[dict[str, Any]] = []
        pending = set(futures.keys())
        while pending:
            if self.stop_event.is_set():
                for future in pending:
                    future.cancel()
                break

            done, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
            for future in done:
                task = futures[future]
                try:
                    result = future.result()
                except BaseException as exc:
                    result = self.exception_result(task, exc)
                results.append(result)
                self.write_result(result)

        return results

    def apply_results(
        self,
        individuals: list[Any],
        results: list[dict[str, Any]],
        generation: int,
    ):
        by_individual_id = {result["individual_id"]: result for result in results}
        for idx, ind in enumerate(individuals, start=1):
            result = by_individual_id.get(idx)
            if result is None:
                result = self.missing_result(generation=generation, individual_id=idx, ind=ind)
            ind.fitness.values = (float(result.get("fitness", INVALID_RUNTIME_FITNESS)),)
            ind.log_dir = result.get("log_dir")
            ind.evaluation_result = result.get("eval_result", {})

    def write_result(self, result: dict[str, Any]):
        test_log_dir = Path(self.config["test_log_dir"])
        fitness_function = self.config["fitness_function"]
        if result.get("run_status") == "ok":
            EvoLogger.write_result_to_csv(
                result,
                fitness_function,
                test_log_dir / "evo_result.csv",
            )
        else:
            EvoLogger.write_excluded_run_to_csv(
                result,
                fitness_function,
                test_log_dir / "evo_excluded_runs.csv",
            )

    def exception_result(self, task: EvaluationTask, exc: BaseException) -> dict[str, Any]:
        reason = f"worker_exception:{type(exc).__name__}"
        self.log(
            f"Task G{task.generation}T{task.individual_id} failed in worker: "
            f"{type(exc).__name__}: {exc}"
        )
        return {
            "generation": task.generation,
            "individual_id": task.individual_id,
            "fitness": INVALID_RUNTIME_FITNESS,
            "eval_result": {
                "runtime_invalid": True,
                "runtime_invalid_reason": reason,
                "worker_exception": str(exc),
            },
            "log_dir": str(Path(self.config["test_log_dir"]) / f"G{task.generation}T{task.individual_id}"),
            "genes": task.genes,
            "run_status": "worker_exception",
            "runtime_invalid": True,
            "runtime_invalid_reason": reason,
            "attempts_used": 0,
            "retcode": None,
        }

    def missing_result(self, generation: int, individual_id: int, ind: Any) -> dict[str, Any]:
        genes = ind.to_dict() if hasattr(ind, "to_dict") else list(ind)
        return {
            "generation": generation,
            "individual_id": individual_id,
            "fitness": INVALID_RUNTIME_FITNESS,
            "eval_result": {
                "runtime_invalid": True,
                "runtime_invalid_reason": "missing_result",
            },
            "log_dir": str(Path(self.config["test_log_dir"]) / f"G{generation}T{individual_id}"),
            "genes": genes,
            "run_status": "missing_result",
            "runtime_invalid": True,
            "runtime_invalid_reason": "missing_result",
            "attempts_used": 0,
            "retcode": None,
        }

    def summary(
        self,
        status: str,
        started_at: float,
        evaluation_count: int,
        hof: tools.HallOfFame,
    ) -> RunnerSummary:
        best_fitness = None
        best_log_dir = None
        if len(hof) > 0:
            best_ind = hof[0]
            if best_ind.fitness.valid:
                best_fitness = float(best_ind.fitness.values[0])
            best_log_dir = getattr(best_ind, "log_dir", None)

        return RunnerSummary(
            experiment_id=self.experiment_id,
            label=self.label,
            status=status,
            evaluations=evaluation_count,
            elapsed_sec=time.time() - started_at,
            best_fitness=best_fitness,
            best_log_dir=best_log_dir,
        )


def runner_thread_main(
    config: dict[str, Any],
    pool: SharedEvaluationPool,
    stop_event: threading.Event,
    summaries: "queue.Queue[RunnerSummary]",
    errors: "queue.Queue[tuple[str, str]]",
):
    runner = ExperimentRunner(config, pool, stop_event)
    try:
        summaries.put(runner.run())
    except BaseException:
        stop_event.set()
        errors.put((runner.experiment_id, traceback.format_exc()))


def install_signal_handlers(stop_event: threading.Event, pool: SharedEvaluationPool):
    global _active_pool, _main_stop_event
    _active_pool = pool
    _main_stop_event = stop_event
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def signal_handler(signum, frame):
    global _signal_count
    _signal_count += 1
    log_line(f"\nReceived signal {signum}; stopping runners...")
    if _main_stop_event is not None:
        _main_stop_event.set()
    if _force_exit_on_second_sigint and _signal_count >= 2 and _active_pool is not None:
        log_line("Second signal received; terminating evaluation worker processes.")
        _active_pool.force_terminate()


def run_config_threads(
    run_configs: list[dict[str, Any]],
    pool: SharedEvaluationPool,
    stop_event: threading.Event,
    config_thread_limit: int,
) -> tuple[list[RunnerSummary], list[tuple[str, str]]]:
    pending = deque(run_configs)
    active: list[threading.Thread] = []
    summaries_queue: "queue.Queue[RunnerSummary]" = queue.Queue()
    errors_queue: "queue.Queue[tuple[str, str]]" = queue.Queue()
    terminated_pool = False

    while pending or active:
        while pending and len(active) < config_thread_limit and not stop_event.is_set():
            config = pending.popleft()
            thread = threading.Thread(
                target=runner_thread_main,
                args=(config, pool, stop_event, summaries_queue, errors_queue),
                name=f"runner-{config['experiment_id']}",
                daemon=False,
            )
            thread.start()
            active.append(thread)
            log_line(f"[scheduler] Started runner {config['experiment_id']}")

        still_active = []
        for thread in active:
            thread.join(timeout=0.1)
            if thread.is_alive():
                still_active.append(thread)
        active = still_active

        if stop_event.is_set() and not terminated_pool:
            terminated_pool = True
            pool.force_terminate()

        if not active and stop_event.is_set():
            break

        if pending or active:
            time.sleep(0.2)

    summaries: list[RunnerSummary] = []
    while not summaries_queue.empty():
        summaries.append(summaries_queue.get())

    errors: list[tuple[str, str]] = []
    while not errors_queue.empty():
        errors.append(errors_queue.get())

    return summaries, errors


def main() -> int:
    global _force_exit_on_second_sigint
    dirs = get_dirs(__file__)
    config_file = Path(dirs["cur_dir"]) / "run_evotests.yaml"

    try:
        config = load_config(config_file)
        validate_config(config)
    except (FileNotFoundError, yaml.YAMLError, ValueError) as exc:
        log_line(f"Configuration Error: {exc}")
        log_line(f"Expected config file at: {config_file}")
        return 1

    parallel_mode = get_parallel_mode(config)
    max_concurrent_tasks = get_max_concurrent_tasks(config)
    run_configs, root_log_dir = build_run_configs(config, dirs)
    if not run_configs:
        log_line("No run configurations were generated.")
        return 1

    if parallel_mode == "serial":
        config_thread_limit = 1
    else:
        config_thread_limit = int(config.get("max_config_threads") or len(run_configs))
        config_thread_limit = max(1, min(config_thread_limit, len(run_configs)))

    print_config_summary(
        config,
        run_configs,
        root_log_dir,
        max_concurrent_tasks,
        config_thread_limit,
    )

    setup_deap_types()

    for image in sorted({run_config["ripple_image"] for run_config in run_configs}):
        setup_docker_images(image, dirs["rocket_dir"])

    stop_event = threading.Event()
    _force_exit_on_second_sigint = bool(config.get("force_exit_on_second_sigint", False))
    pool = SharedEvaluationPool(max_workers=max_concurrent_tasks)
    install_signal_handlers(stop_event, pool)

    try:
        pool.warm_up()
        summaries, errors = run_config_threads(
            run_configs,
            pool,
            stop_event,
            config_thread_limit,
        )
    finally:
        if stop_event.is_set():
            pool.force_terminate()
        pool.shutdown(
            wait_for_workers=not stop_event.is_set(),
            cancel_futures=stop_event.is_set(),
        )

    if errors:
        log_line("\n=== Runner Errors ===")
        for experiment_id, tb in errors:
            log_line(f"\n[{experiment_id}]\n{tb}")
        return 1

    log_line("\n=== run_evotests2 Summary ===")
    for summary in sorted(summaries, key=lambda item: item.experiment_id):
        best = "N/A" if summary.best_fitness is None else f"{summary.best_fitness:.6g}"
        log_line(
            f"[{summary.experiment_id}] status={summary.status} "
            f"evals={summary.evaluations} elapsed={summary.elapsed_sec:.1f}s "
            f"best={best}"
        )

    if stop_event.is_set():
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
