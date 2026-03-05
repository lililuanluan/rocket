"""
Parallel version of evotest using DEAP for evolutionary testing.

This module supports running multiple test instances in parallel, each with:
- Isolated gRPC ports
- Isolated Docker container names
- Isolated network port ranges
- Isolated log directories
"""

import yaml
import os
import sys
from pathlib import Path
from evaluate import evaluate_log
import subprocess
import shutil
from datetime import datetime
import random
import numpy as np
import csv
import signal
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
import multiprocessing as mp
import tempfile
import copy

# DEAP imports
from deap import base, creator, tools, algorithms
from utils import *
from configs import get_configs
from evologger import EvoLogger


from evo import encoding
from evo.run_rocket import run_rocket_and_evaluate
import threading


"""The `main` function will call :func:`get_configs` and receive a single
dictionary containing all parameters.  We avoid any global `dirs` variable and
do not use the EvotestConfig class at all.  """


stop_event = threading.Event()
_signal_count = 0


def signal_handler(signum, frame):
    """Handle SIGINT/SIGTERM by requesting a graceful stop."""
    global _signal_count
    _signal_count += 1
    stop_event.set()
    if _signal_count >= 2:
        print(f"\nReceived signal {signum} again, forcing immediate exit.")
        raise SystemExit(130)


def _force_terminate_executor(executor: ProcessPoolExecutor):
    # Best-effort hard stop for running worker processes.
    procs = getattr(executor, "_processes", {}) or {}
    for p in procs.values():
        try:
            if p.is_alive():
                p.terminate()
        except Exception:
            pass


def setup_deap_types():
    """设置 DEAP 的类型系统"""
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


def evaluate_individual_worker(args):
    (
        individual_genes,
        generation,
        individual_id,
        config,
        test_log_dir,
        max_ledger_seq,
        fitness_function,
        logs_dir,
        output_screen,
        base_port_number,
    ) = args

    # choose a fresh seed per evaluation, ignore whatever was in config
    seed = random.randrange(2**31)

    # build cluster/log identifiers exactly as before
    ind_id = f"G{generation}T{individual_id}"
    full_log_dir = Path(logs_dir) / str(test_log_dir) / ind_id

    cluster_id = make_cluster_id(logs_dir, str(test_log_dir), ind_id)

    # call shared helper; it will take care of container cleanup, network
    # config file generation, and evaluation of the log.
    result = run_rocket_and_evaluate(
        log_dir=full_log_dir,
        cluster_id=cluster_id,
        max_ledger_seq=max_ledger_seq,
        seed=seed,
        encoding=individual_genes,
        rocket_dir=get_dirs(__file__)["rocket_dir"],
        tmp_dir=get_dirs(__file__)["tmp_dir"],
        byzz_min_seq=config.get("byzz_min_seq", 5),
        byzz_max_seq=config.get("byzz_max_seq", 10),
        output_screen=output_screen,
        timeout_sec_per_seq=config.get("timeout_per_seq", 30),
        network_yaml=get_dirs(__file__)["cur_dir"]
        / config.get("base_network_config_yaml", "network.yaml"),
        base_port_number=base_port_number,
        strategy_name=get_strategy_name(config.get("strategy", "")),
        min_delay_ms=config.get("min_delay_ms"),
        max_delay_ms=config.get("max_delay_ms"),
        ripple_image=config.get("ripple_image", ""),
        rust_log_level=config.get("rust_log_level", "info"),
        fitness_function=fitness_function,
        individual_timeout_sec=config.get("individual_timeout_sec", 300),
    )

    fitness = result.get("fitness", 0.0)
    eval_result = result.get("eval_result", {})
    print(f"[{cluster_id}] Fitness: {fitness}")

    return {
        "generation": generation,
        "individual_id": individual_id,
        "fitness": fitness,
        "eval_result": eval_result,
        "log_dir": str(full_log_dir),
        "genes": individual_genes,
    }


def parallel_evaluate_population(
    population,
    generation,
    config,
):
    # extract parameters from config dictionary (seed ignored)
    base_network_config = config.get("base_network_config", {})
    test_log_dir = Path(config.get("test_log_dir", ""))
    max_ledger_seq = config.get("max_ledger_seq")
    fitness_function = config.get("fitness_function")
    logs_dir = config.get("logs_dir")
    max_workers = config.get("max_parallel_workers")

    # normalise test_log_dir for workers
    test_log_dir_str = str(test_log_dir)
    print(f"using test_log_dir: {test_log_dir_str}")

    # prepare task parameters
    num_nodes = base_network_config.get("number_of_nodes", 0) or 1
    ports_per_test = 1 + num_nodes * 4
    base_pop = config.get("base_port_population", 60000)
    population_size = config.get("population_size", len(population))

    tasks = []
    output_screen_flag = True if max_workers == 1 else False
    for idx, ind in enumerate(population):
        # ensure that each evaluation gets its own slice of the port space.
        offset_index = generation * population_size + idx
        base_port_number = base_pop + offset_index * ports_per_test
        # seed value passed but ignored by worker
        tasks.append(
            (
                ind.to_dict(),
                generation,
                idx + 1,
                config,
                test_log_dir_str,
                max_ledger_seq,
                fitness_function,
                str(logs_dir),
                output_screen_flag,
                base_port_number,
            )
        )

    results = []

    # 使用进程池并行评估
    # 注意：由于 Docker 资源限制，我们按批次处理
    batch_size = max_workers
    for batch_start in range(0, len(tasks), batch_size):
        if stop_event.is_set():
            print("Stop requested, no more batches will be scheduled.")
            break
        batch_end = min(batch_start + batch_size, len(tasks))
        batch_tasks = tasks[batch_start:batch_end]

        print(
            f"\n=== Evaluating batch {batch_start//batch_size + 1} (individuals {batch_start+1}-{batch_end}) ==="
        )

        executor = ProcessPoolExecutor(max_workers=min(len(batch_tasks), max_workers))
        futures = [executor.submit(evaluate_individual_worker, task) for task in batch_tasks]
        try:
            pending = set(futures)
            while pending:
                if stop_event.is_set():
                    break
                done, pending = wait(
                    pending, timeout=0.5, return_when=FIRST_COMPLETED
                )
                for future in done:
                    try:
                        result = future.result()
                        results.append(result)
                        EvoLogger.write_result_to_csv(
                            result, fitness_function, Path(test_log_dir) / "evo_result.csv"
                        )
                    except Exception as e:
                        print(f"Error processing evaluation result: {e}")
                        import traceback

                        traceback.print_exc()
        finally:
            if stop_event.is_set():
                for f in futures:
                    f.cancel()
                _force_terminate_executor(executor)
                executor.shutdown(wait=False, cancel_futures=True)
            else:
                executor.shutdown(wait=True)

    return results


def get_encoding_cls(strategy: str):
    cls_name = f"{strategy}Encoding"
    return getattr(encoding, cls_name)


def sample_individual(configs: dict):
    strategy = configs["strategy"]
    encoding_cls = get_encoding_cls(strategy)
    return encoding_cls.sample(configs)


def main(configs: dict):
    stop_event.clear()

    EvoLogger.init_log(configs["test_log_dir"])

    # 重置全局变量
    evaluation_cnt = 0
    # (the entire configuration is already in the `configs` dict)

    # register signal handlers only in the main process
    # (worker processes must not install these handlers)
    if mp.current_process().name == "MainProcess":
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

    # build_interceptor(interceptor_dir=configs["interceptor_dir"], cargo_clean=False) # TODO build outside, otherwise race
    setup_docker_images(configs["ripple_image"], configs["rocket_dir"])
    setup_deap_types()

    lambda_ = configs["population_size"]
    mu = min(lambda_, configs["mu"])
    max_generation = configs["max_generation"]

    strategy = configs["strategy"]
    encoding_cls = get_encoding_cls(strategy)

    # 设置 DEAP toolbox
    toolbox = base.Toolbox()

    # 注册遗传算法操作
    toolbox.register("individual", sample_individual, configs)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)

    toolbox.register("mate", encoding_cls.mate)
    toolbox.register("mutate", encoding_cls.mutate)
    toolbox.register("select", tools.selBest)

    # 统计信息
    stats = tools.Statistics(lambda ind: ind.fitness.values)
    stats.register("avg", np.mean)
    stats.register("std", np.std)
    stats.register("min", np.min)
    stats.register("max", np.max)

    # 创建 HallOfFame 保存最佳个体
    hof = tools.HallOfFame(1)

    # 创建 logbook
    logbook = tools.Logbook()
    logbook.header = ["gen", "nevals"] + stats.fields

    print(f"=== Initialization (Generation 0) ===")
    # 初始化种群
    population = toolbox.population(n=lambda_)

    # 并行评估初始种群
    results = parallel_evaluate_population(
        population,
        generation=0,
        config=configs,
    )
    if stop_event.is_set():
        print("Stop requested during generation 0.")
        return population, None, hof

    evaluation_cnt += len(results)

    # 更新个体的 fitness
    for result in results:
        ind_idx = result["individual_id"] - 1
        population[ind_idx].fitness.values = (result["fitness"],)
        population[ind_idx].log_dir = result["log_dir"]
        population[ind_idx].evaluation_result = result["eval_result"]

    # 更新 HallOfFame 和统计
    hof.update(population)
    record = stats.compile(population)
    logbook.record(gen=0, nevals=len(population), **record)
    print(logbook.stream)

    # 选择 mu 个父代
    population = toolbox.select(population, mu)

    # 主进化循环
    for gen in range(1, max_generation + 1):
        if stop_event.is_set():
            print("Stop requested. Exiting evolution loop.")
            break
        print(f"\n=== Generation {gen} ===")

        # 生成子代
        offspring = algorithms.varOr(population, toolbox, lambda_, cxpb=0.7, mutpb=0.3)

        # 获取未评估的个体
        invalid_ind = [ind for ind in offspring if not ind.fitness.valid]

        if invalid_ind:
            # 并行评估子代
            results = parallel_evaluate_population(
                invalid_ind,
                generation=gen,
                config=configs,
            )
            if stop_event.is_set():
                print("Stop requested during offspring evaluation.")
                break

            evaluation_cnt += len(results)

            # 更新个体的 fitness
            for result in results:
                ind_idx = result["individual_id"] - 1
                invalid_ind[ind_idx].fitness.values = (result["fitness"],)
                invalid_ind[ind_idx].log_dir = result["log_dir"]
                invalid_ind[ind_idx].evaluation_result = result["eval_result"]

        # (μ+λ) 选择
        population = toolbox.select(population + offspring, mu)

        # 更新 HallOfFame 和统计
        hof.update(population)
        record = stats.compile(population)
        logbook.record(gen=gen, nevals=len(invalid_ind), **record)
        print(logbook.stream)

    # 最终总结
    print("\n=== Evolution Complete ===")
    print(f"Total evaluations: {evaluation_cnt}")

    best_ind = hof[0]
    print(f"\nBest individual:")
    print(f"  Fitness: {best_ind.fitness.values[0]}")
    print(
        f"  Log directory: {best_ind.log_dir if hasattr(best_ind, 'log_dir') else 'N/A'}"
    )
    print(f"  Encoding (first 10 genes): {list(best_ind)[:10]}...")

    if hasattr(best_ind, "evaluation_result") and best_ind.evaluation_result:
        result = best_ind.evaluation_result
        print(f"  Mean validation time: {result.get('mean_validation_time')}")
        print(f"  Propose set count: {result.get('num_propose_set')}")
        print(f"  Total failures: {result.get('total_failures')}")

    print("\n=== Evolution Statistics ===")
    print(logbook)

    return population, logbook, hof


if __name__ == "__main__":
    try:
        cfg = get_configs()
        main(cfg)
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
        raise SystemExit(130)
    except Exception as e:
        print(f"Error during evolution: {e}")
        import traceback

        traceback.print_exc()
        raise e
