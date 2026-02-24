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
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing as mp
import tempfile
import copy

# DEAP imports
from deap import base, creator, tools, algorithms
from utils import *
from configs import get_configs
from cleanup import cleanup_all_interceptor_processes, cleanup_all_docker_containers, cleanup_instance_docker_containers
from evologger import EvoLogger


from evo import encodings


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


def run_rocket_instance(
    instance_id: str,
    log_dir: str,  # <name>/G{gen}T{ind}/
    max_ledger_seq: int,
    seed: int,
    encoding: dict,
    config: dict,
    base_network_config: dict,
    port_offset: int,
    dirs=None,
    output_screen=False,
):
    """运行单个 Rocket 实例

    Args:
        instance_id: 实例 ID，格式为 G{gen}T{ind}，用于隔离容器
        log_dir: 日志目录
        max_ledger_seq: 最大账本序列号
        seed: 随机种子
        encoding: 编码（延迟策略）
        config: 策略配置
        base_network_config: 基础网络配置
        port_offset: 端口偏移量，用于隔离网络端口
        output_screen: 如果为 True，将把 rocket 的 stdout/stderr 打印到屏幕；否则重定向到日志文件
    """
    # allow caller to pass directories or recompute them lazily
    if dirs is None:
        dirs = get_dirs(__file__)
    os.chdir(dirs["rocket_dir"])
    py = sys.executable

    # 计算 gRPC 端口（使用 port_offset 而不是 instance_id）
    # grpc_base_port is provided via the global configuration dict; default
    # to 50051 for backward compatibility.  individual workers will add their
    # own port_offset (derived from their index) to this base.
    grpc_base = config.get("grpc_base_port", 50051)
    grpc_port = grpc_base + port_offset

    # 清理该实例的旧容器
    cleanup_instance_docker_containers(instance_id)

    byzz_min_seq = config.get("byzz_min_seq", 5)
    byzz_max_seq = config.get("byzz_max_seq", 10)
    timeout_sec_per_seq = config.get("timeout_sec_per_seq", 30)
    
    # 生成实例专属的网络配置（使用 port_offset 计算端口偏移）
    instance_network_config = generate_instance_network_config(port_offset, base_network_config)
    
    # 确保临时目录存在
    tmp_dir = dirs["tmp_dir"]
    tmp_dir.mkdir(parents=True, exist_ok=True)
    
    # 写入实例专属的网络配置文件（放到 tmp 目录）
    instance_network_yaml = tmp_dir / f"network_{instance_id}.yaml"
    with open(instance_network_yaml, "w") as f:
        yaml.dump(instance_network_config, f)

    strategy_name = get_strategy_name(config.get("strategy", "EvoDelayStrategy"))
    strategy_yaml = tmp_dir / f"{strategy_name}_{instance_id}.yaml"
    with open(strategy_yaml, "w") as f:
        yaml.dump(
            {
                "seed": seed,
                "encoding": encoding,
                "byzz_min_seq": byzz_min_seq,
                "byzz_max_seq": byzz_max_seq,
                "min_delay_ms": config["min_delay_ms"],
                "max_delay_ms": config["max_delay_ms"],
                "timeout_sec_per_seq": timeout_sec_per_seq,
            },
            f,
        )

    cmd = [
        py,
        "-m",
        "rocket_controller",
        strategy_name,
        "--config",
        str(strategy_yaml),
        "--network_config",
        str(instance_network_yaml),
        "--log-dir",
        log_dir,
        "--max-iteration",
        str(1),
        "--max-ledger-seq",
        str(max_ledger_seq),
        "--grpc-port",
        str(grpc_port),
        "--instance-id",
        str(instance_id),
        "--rippled-img",
        str(config.get("ripple-image", "")),
    ]

    if output_screen:
        print(f"[{instance_id}] \n\tRunning command: {' '.join(cmd)}\n\toutput: (printed to screen)")
    else:
        print(f"[{instance_id}] \n\tRunning command: {' '.join(cmd)}\n\tstderr saved to {dirs['logs_dir'] / log_dir / 'rocket_stderr.log'}")
    env = os.environ.copy()
    env["RUST_BACKTRACE"] = "full"
    env["RUST_LOG"] = config.get("rust_log_level", "")
    
    # 将输出重定向到 log 文件夹，或直接打印到屏幕
    full_log_dir = dirs["logs_dir"] / log_dir
    full_log_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = full_log_dir / "rocket_stdout.log"
    stderr_log = full_log_dir / "rocket_stderr.log"

    if output_screen:
        # Print to terminal (inherit parent's stdout/stderr)
        retcode = subprocess.call(cmd, env=env)
    else:
        with open(stdout_log, "w") as stdout_f, open(stderr_log, "w") as stderr_f:
            retcode = subprocess.call(cmd, env=env, stdout=stdout_f, stderr=stderr_f)

    if retcode != 0:
        print(f"[{instance_id}] Rocket exited with code {retcode}")
    else:
        print(f"[{instance_id}] Rocket finished successfully")

    os.chdir(dirs["cur_dir"])
    
    # 清理临时配置文件
    try:
        instance_network_yaml.unlink()
        strategy_yaml.unlink()
    except:
        pass


def evaluate_individual_worker(args):
    """工作进程中评估个体的函数
    
    这个函数在单独的进程中运行，用于并行评估
    """
    (
        individual_genes,
        generation,
        individual_id,
        port_offset,
        config,
        base_network_config,
        test_log_id,
        max_ledger_seq,
        seed,
        fitness_function,
        byzz_nodes,
        logs_dir,
        output_screen,
    ) = args
    
    # 生成 log 目录和 instance_id。若提供了 run_id，则将其作为前缀，
    # 这样容器名里会携带 run_id 以实现跨进程隔离。
    run_id = config.get("run_id", "")
    base_id = f"G{generation}T{individual_id}-F-{fitness_function}-S-{config['strategy']}"
    instance_id = f"{run_id}-{base_id}" if run_id else base_id
    log_dir = f"{test_log_id}/{instance_id}/"
    
    # 运行 Rocket
    run_rocket_instance(
        instance_id=instance_id,
        log_dir=log_dir,
        max_ledger_seq=max_ledger_seq,
        seed=seed,
        encoding=individual_genes,
        config=config,
        base_network_config=base_network_config,
        port_offset=port_offset,
        output_screen=output_screen,
    )

    # 评估结果
    eval_result = evaluate_log(Path(logs_dir) / log_dir, byzz_nodes=byzz_nodes)
    
    if fitness_function in eval_result:
        fitness = eval_result[fitness_function] if eval_result[fitness_function] else 0.0
    else:
        fitness = 0.0
    
    print(f"[{instance_id}] Fitness: {fitness}")

    return {
        "generation": generation,
        "individual_id": individual_id,
        "fitness": fitness,
        "eval_result": eval_result,
        "log_dir": log_dir,
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
        其他参数: 配置信息
        max_workers: 最大并行工作进程数
    
    Returns:
        results: 评估结果列表
    """
    # test_log_dir is a Path like .../logs/<datetime>
    # use only the run-directory name (the datetime identifier) as the test_log_id
    # (previous code used test_log_dir.parent which caused instance logs to be
    # written to logs/ instead of logs/<datetime>/)
    test_log_dir = Path(test_log_dir)
    test_log_id = test_log_dir.name
    print(f"test_log_id: {test_log_id} (run dir: {test_log_dir})")
    # 准备任务参数
    tasks = []
    output_screen_flag = True if max_workers == 1 else False
    for idx, ind in enumerate(population):
        port_offset = idx % max_workers  # 用于端口隔离
        tasks.append((
            ind.to_dict(),  # 个体基因
            generation,
            idx + 1,  # individual_id 从 1 开始
            port_offset,
            config,
            base_network_config,
            test_log_id,
            max_ledger_seq,
            seed,
            fitness_function,
            byzz_nodes,
            str(logs_dir),
            output_screen_flag,
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
            futures = {executor.submit(evaluate_individual_worker, t): i for i, t in enumerate(batch_tasks)}
            for future in as_completed(futures):
                try:
                    result = future.result()
                    results.append(result)
                    
                    # 实时写入 CSV
                    # `test_log_dir` is passed as an argument to this function
                    EvoLogger.write_result_to_csv(result, fitness_function, Path(test_log_dir) / "evo_result.csv")
                    
                except Exception as e:
                    print(f"Error evaluating individual: {e}")
                    import traceback
                    traceback.print_exc()
    
    return results

def get_encoding_cls(strategy: str):
    cls_name = f"{strategy}Encoding"
    return getattr(encodings, cls_name)

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
