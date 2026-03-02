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
import atexit
from concurrent.futures import ProcessPoolExecutor
import multiprocessing as mp
import tempfile
import copy

# DEAP imports
from deap import base, creator, tools, algorithms
from utils import *
from configs import get_configs
from cleanup import cleanup_all_interceptor_processes, cleanup_all_docker_containers, cleanup_instance_docker_containers
from evologger import EvoLogger


from evo import encoding
from evo.run_rocket import run_rocket_and_evaluate


"""The `main` function will call :func:`get_configs` and receive a single
dictionary containing all parameters.  We avoid any global `dirs` variable and
do not use the EvotestConfig class at all.  """




def signal_handler(signum, frame):
    """处理 Ctrl+C 信号"""
    print("\n\n⚠️  Received interrupt signal (Ctrl+C)")
    cleanup_all_interceptor_processes()
    cleanup_all_docker_containers()
    sys.exit(130)

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

def generate_instance_network_config(instance_id: int, base_config: dict) -> dict:
    """为每个实例生成独立的网络配置

    NOTE: the first parameter is *not* a literal identifier but the
    numerical port offset assigned by the caller (usually idx % max_workers).

    Args:
        instance_id: integer offset used to shift all base ports (0, 1, 2, ...).
        base_config: 基础网络配置

    Returns:
        修改后的网络配置，端口偏移了 instance_id * 100
    """
    config = copy.deepcopy(base_config)
    offset = instance_id * 100
    
    config['base_port_peer'] = base_config.get('base_port_peer', 60000) + offset
    config['base_port_ws'] = base_config.get('base_port_ws', 61000) + offset
    config['base_port_ws_admin'] = base_config.get('base_port_ws_admin', 62000) + offset
    config['base_port_rpc'] = base_config.get('base_port_rpc', 63000) + offset
    
    return config


def evaluate_individual_worker(args):
    """Worker function executed inside a separate process.

    The caller prepares a tuple containing all of the information needed to
    invoke ``run_rocket_and_evaluate``.  The worker computes a per‑run base
    port number from the ``base_port_population`` supplied in the
    configuration, then forwards the rest of the arguments directly.  The
    return value mirrors the structure that the evolution loop expects.

    ``run_rocket_and_evaluate`` is imported from ``evo.run_rocket`` and
    encapsulates all of the Docker/container/port/logging setup we need for
    an individual evaluation.  By centralising the call here we avoid
    duplicating that logic in both the sequential and parallel runners.
    """
    (
        individual_genes,
        generation,
        individual_id,
        config,
        base_network_config,
        test_log_dir,
        max_ledger_seq,
        seed,
        fitness_function,
        logs_dir,
        output_screen,
        base_port_number,
    ) = args

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
        network_yaml=get_dirs(__file__)["cur_dir"] / config.get("base_network_config_yaml", "network.yaml"),
        base_port_number=base_port_number,
        strategy_name=get_strategy_name(config.get("strategy", "")),
        min_delay_ms=config.get("min_delay_ms"),
        max_delay_ms=config.get("max_delay_ms"),
        ripple_image=config.get("ripple_image", ""),
        rust_log_level=config.get("rust_log_level", "info"),
        fitness_function=fitness_function,
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
    base_network_config,
    test_log_dir,
    max_ledger_seq,
    seed,
    fitness_function,
    byzz_nodes,
    logs_dir,
    max_workers,
):
    """并行评估种群
 
    Args:
        population: 需要评估的个体列表
        generation: 当前代数
        config: 全部配置字典；其中 ``base_port_population`` 将被用来
            计算每个个体的 ``base_port_number`` 参数，从而为每次调用
            ``run_rocket_and_evaluate`` 分配独立的端口范围。
        base_network_config: 网络配置
        test_log_dir: 用于放置单个测试日志的顶层目录
        max_ledger_seq: 传递给 rocket 的最大账本次数
        seed: 随机种子
        fitness_function: 当前使用的适应度函数名
        byzz_nodes: （未使用）拜占庭节点列表，保留参数兼容
        logs_dir: 顶层日志目录
        max_workers: 最大并行工作进程数
    
    Returns:
        results: 评估结果列表
    """
    test_log_dir = Path(test_log_dir)
    # keep full path string for worker processes
    test_log_dir_str = str(test_log_dir)
    print(f"using test_log_dir: {test_log_dir_str}")
    # 准备任务参数
    # figure out how many ports each evaluation will consume so that we can
    # hand out non‑overlapping ranges.  ``run_rocket_and_evaluate`` expects a
    # single base port and will internally space peer/ws/ws_admin/rpc and
    # grpc as 0..4*num_nodes.
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
        tasks.append((
            ind.to_dict(),
            generation,
            idx + 1,
            config,
            base_network_config,
            test_log_dir_str,
            max_ledger_seq,
            seed,
            fitness_function,
            str(logs_dir),
            output_screen_flag,
            base_port_number,
        ))
    
    results = []
    
    # 使用进程池并行评估
    # 注意：由于 Docker 资源限制，我们按批次处理
    batch_size = max_workers
    for batch_start in range(0, len(tasks), batch_size):
        batch_end = min(batch_start + batch_size, len(tasks))
        batch_tasks = tasks[batch_start:batch_end]
        
        print(f"\n=== Evaluating batch {batch_start//batch_size + 1} (individuals {batch_start+1}-{batch_end}) ===")
        
        with ProcessPoolExecutor(max_workers=min(len(batch_tasks), max_workers)) as executor:
            # ``map`` 提交所有任务并按顺序返回结果，我们只需
            # 遍历它并记录输出即可；如果某个评估抛出异常，
            # 该异常会在迭代时重新抛出，方便上层处理。
            for result in executor.map(evaluate_individual_worker, batch_tasks):
                 try:
                     results.append(result)
                     EvoLogger.write_result_to_csv(
                         result, fitness_function, Path(test_log_dir) / "evo_result.csv"
                     )
                 except Exception as e:
                     # in practice the only danger here is if the result
                     # itself is None or malformed; most evaluation errors are
                     # raised above.  log and keep going.
                     print(f"Error processing evaluation result: {e}")
                     import traceback
                     traceback.print_exc()
  
    return results

def get_encoding_cls(strategy: str):
    cls_name = f"{strategy}Encoding"
    return getattr(encoding, cls_name)

def sample_individual(configs: dict):
    strategy = configs["strategy"]
    encoding_cls = get_encoding_cls(strategy)
    return encoding_cls.sample(configs)


def main(configs: dict):
    
    EvoLogger.init_log(configs["test_log_dir"])

    # 重置全局变量
    evaluation_cnt = 0
    # (the entire configuration is already in the `configs` dict)

    # register signal handlers / atexit only in the main process
    # (worker processes must not install these handlers)
    if mp.current_process().name == "MainProcess":
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        atexit.register(cleanup_all_interceptor_processes)

    # build_interceptor(interceptor_dir=configs["interceptor_dir"], cargo_clean=False) # TODO build outside, otherwise race
    setup_docker_images(configs["ripple_image"], configs["rocket_dir"])
    setup_deap_types()

    # 读取配置
    random.seed(configs["seed"])
    np.random.seed(configs["seed"])



    lambda_ = configs["population_size"]
    mu = min(lambda_, configs["mu"])
    max_generation = configs["max_generation"]
    fitness_function = configs["fitness_function"]

    num_nodes = configs.get("number_of_nodes")
    encoding_len = num_nodes * (num_nodes - 1) * 7
    # use the CLI parameter names directly (no intermediate mapping)
    delay_min = configs.get("min_delay_ms")
    delay_max = configs.get("max_delay_ms")


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
        config=configs,  # now use entire dict instead of a nested `config` attr
        base_network_config=configs.get("base_network_config"),
        test_log_dir=configs.get("test_log_dir"),
        max_ledger_seq=configs.get("max_ledger_seq"),
        seed=configs.get("seed"),
        fitness_function=fitness_function,
        byzz_nodes=configs.get("byzz_nodes"),
        logs_dir=configs.get("logs_dir"),
        max_workers=configs.get("max_parallel_workers"),
    )

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
                base_network_config=configs.get("base_network_config"),
                test_log_dir=configs.get("test_log_dir"),
                max_ledger_seq=configs.get("max_ledger_seq"),
                seed=configs.get("seed"),
                fitness_function=fitness_function,
                byzz_nodes=configs.get("byzz_nodes"),
                logs_dir=configs.get("logs_dir"),
                max_workers=configs.get("max_parallel_workers"),
            )

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
    print(f"  Log directory: {best_ind.log_dir if hasattr(best_ind, 'log_dir') else 'N/A'}")
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
    except Exception as e:
        print(f"Error during evolution: {e}")
        import traceback
        traceback.print_exc()
        raise e
