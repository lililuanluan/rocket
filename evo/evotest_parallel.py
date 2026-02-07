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
import subprocess
import shutil
from rebuild_interceptor import rebuild_interceptor_with
from datetime import datetime
from evaluate import evaluate_log
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

# dirs
CUR_DIR = Path(__file__).parent
ROCKET_DIR = CUR_DIR.parent
INTERCEPTOR_DIR = ROCKET_DIR / "rocket_interceptor"
LOGS_DIR = ROCKET_DIR / "logs"
TMP_DIR = CUR_DIR / "tmp"  # 临时配置文件目录

with open(CUR_DIR / "network.yaml", "r") as f:
    network_config = yaml.safe_load(f)
    NUMBER_OF_NODES = network_config["number_of_nodes"]


# 全局变量用于存储配置
ENCODING_MIN = 0
ENCODING_MAX = 4000
ENCODING_LENGTH = 0
START_DATETIME = ""
SEED = 42
MAX_ITERATION = 1
MAX_LEDGER_SEQ = 5
FITNESS_FUNCTION = "time"
EVALUATION_COUNTER = 0
MAX_PARALLEL_WORKERS = 4

# 用于记录每代的 fitness 数据
GENERATION_DATA = []

# CSV 文件路径（用于实时写入）
CSV_FILE_PATH = None
CSV_LOCK = None

BYZZ_NODES = None


def cleanup_all_interceptor_processes():
    """清理所有 rocket-interceptor 进程"""
    try:
        print("\n🧹 Cleaning up all rocket-interceptor processes...")
        subprocess.run(
            ["killall", "-9", "rocket-interceptor"],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )
        print("✓ Cleanup complete")
    except Exception as e:
        print(f"Warning: Could not cleanup processes: {e}")


def cleanup_all_docker_containers():
    """清理所有 validator 容器"""
    try:
        out = subprocess.check_output(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                "name=validator_",
                "--format",
                "{{.Names}}",
            ],
            text=True,
        ).strip()
        if out:
            names = [n for n in out.splitlines() if n]
            for name in names:
                print(f"Stopping and removing container: {name}")
                try:
                    subprocess.run(["docker", "rm", "-f", name], check=True)
                except subprocess.CalledProcessError as e:
                    print(f"Warning: failed to remove {name}: {e}")
    except FileNotFoundError:
        print("docker not found in PATH; skipping validator cleanup")
    except subprocess.CalledProcessError as e:
        print(f"Warning: error while listing validator containers: {e}")


def cleanup_instance_docker_containers(instance_id):
    """清理特定实例的 validator 容器
    
    Args:
        instance_id: 实例 ID，可以是字符串如 "G0T1" 或整数
    """
    try:
        instance_id_str = str(instance_id)
        
        out = subprocess.check_output(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                "name=validator_",
                "--format",
                "{{.Names}}",
            ],
            text=True,
        ).strip()
        if out:
            names = [n for n in out.splitlines() if n]
            for name in names:
                # 匹配包含 _i{instance_id} 后缀的容器
                if f"_i{instance_id_str}" in name:
                    try:
                        subprocess.run(["docker", "rm", "-f", name], check=True,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except subprocess.CalledProcessError:
                        pass
    except Exception:
        pass


def signal_handler(signum, frame):
    """处理 Ctrl+C 信号"""
    print("\n\n⚠️  Received interrupt signal (Ctrl+C)")
    cleanup_all_interceptor_processes()
    cleanup_all_docker_containers()
    sys.exit(130)


# 注册信号处理器和退出清理
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
atexit.register(cleanup_all_interceptor_processes)


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


def setup_interceptor(config):
    """设置 interceptor"""
    ripple_image = config["ripple-image"]

    success = rebuild_interceptor_with(
        img=ripple_image, interceptor_dir=INTERCEPTOR_DIR
    )
    if not success:
        raise RuntimeError("Rebuild interceptor failed")

    target_path = INTERCEPTOR_DIR / "rocket-interceptor"
    assert target_path.exists(), f"Interceptor binary not found at {target_path}"


def setup_docker_images(config):
    """拉取/构建 Docker 镜像"""
    ripple_image = config["ripple-image"]
    if "local" not in ripple_image:
        subprocess.run(["docker", "pull", ripple_image], check=True)

    original_cwd = os.getcwd()
    os.chdir(ROCKET_DIR / "images")
    subprocess.run(["make", "build"], check=True)
    print("✓ Local images built successfully")
    os.chdir(original_cwd)


def get_strategy_name(config):
    strategy = config.get("strategy", "evo")
    if strategy == "random":
        return "RandomByzzStrategy"
    elif strategy == "evo":
        return "EvoDelayStrategy"
    else:
        raise ValueError(f"Unsupported strategy: {strategy}")


def generate_instance_network_config(instance_id: int, base_config: dict) -> dict:
    """为每个实例生成独立的网络配置
    
    Args:
        instance_id: 实例 ID (0, 1, 2, ...)
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
    log_dir: str,
    max_iteration: int,
    max_ledger_seq: int,
    seed: int,
    encoding: list,
    config: dict,
    base_network_config: dict,
    port_offset: int,
):
    """运行单个 Rocket 实例
    
    Args:
        instance_id: 实例 ID，格式为 G{gen}T{ind}，用于隔离容器
        log_dir: 日志目录
        max_iteration: 最大迭代次数
        max_ledger_seq: 最大账本序列号
        seed: 随机种子
        encoding: 编码（延迟策略）
        config: 策略配置
        base_network_config: 基础网络配置
        port_offset: 端口偏移量，用于隔离网络端口
    """
    os.chdir(ROCKET_DIR)
    py = sys.executable
    
    # 计算 gRPC 端口（使用 port_offset 而不是 instance_id）
    grpc_port = 50051 + port_offset
    
    # 清理该实例的旧容器
    cleanup_instance_docker_containers(instance_id)

    byzz_min_seq = config.get("byzz_min_seq", 5)
    byzz_max_seq = config.get("byzz_max_seq", 10)
    timeout_sec_per_seq = config.get("timeout_sec_per_seq", 30)
    
    # 生成实例专属的网络配置（使用 port_offset 计算端口偏移）
    instance_network_config = generate_instance_network_config(port_offset, base_network_config)
    
    # 确保临时目录存在
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    
    # 写入实例专属的网络配置文件（放到 tmp 目录）
    instance_network_yaml = TMP_DIR / f"network_{instance_id}.yaml"
    with open(instance_network_yaml, "w") as f:
        yaml.dump(instance_network_config, f)

    strategy_name = get_strategy_name(config)
    strategy_yaml = TMP_DIR / f"{strategy_name}_{instance_id}.yaml"
    with open(strategy_yaml, "w") as f:
        yaml.dump(
            {
                "seed": seed,
                "encoding": encoding,
                "byzz_min_seq": byzz_min_seq,
                "byzz_max_seq": byzz_max_seq,
                "min_delay_ms": config.get("encoding", {}).get("min_value", 0),
                "max_delay_ms": config.get("encoding", {}).get("max_value", 4000),
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
        str(max_iteration),
        "--max-ledger-seq",
        str(max_ledger_seq),
        "--grpc-port",
        str(grpc_port),
        "--instance-id",
        str(instance_id),
    ]

    print(f"[{instance_id}] Running command: {' '.join(cmd)}")
    env = os.environ.copy()
    env["RUST_BACKTRACE"] = "full"
    env["RUST_LOG"] = config.get("rust_log_level", "")
    env["ROCKET_GRPC_PORT"] = str(grpc_port)
    env["ROCKET_INSTANCE_ID"] = str(instance_id)
    
    # 将输出重定向到 log 文件夹
    full_log_dir = LOGS_DIR / log_dir
    full_log_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = full_log_dir / "rocket_stdout.log"
    stderr_log = full_log_dir / "rocket_stderr.log"
    
    with open(stdout_log, "w") as stdout_f, open(stderr_log, "w") as stderr_f:
        retcode = subprocess.call(cmd, env=env, stdout=stdout_f, stderr=stderr_f)

    if retcode != 0:
        print(f"[{instance_id}] Rocket exited with code {retcode}")
    else:
        print(f"[{instance_id}] Rocket finished successfully")

    os.chdir(CUR_DIR)
    
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
        start_datetime,
        max_iteration,
        max_ledger_seq,
        seed,
        fitness_function,
        byzz_nodes,
        logs_dir,
    ) = args
    
    # 生成 log 目录和 instance_id（使用 G{gen}T{ind} 格式）
    instance_id = f"G{generation}T{individual_id}"
    log_dir = f"{start_datetime}/{instance_id}/"
    
    # 运行 Rocket
    run_rocket_instance(
        instance_id=instance_id,
        log_dir=log_dir,
        max_iteration=max_iteration,
        max_ledger_seq=max_ledger_seq,
        seed=seed,
        encoding=individual_genes,
        config=config,
        base_network_config=base_network_config,
        port_offset=port_offset,
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


def init_csv_file(output_dir):
    """初始化 CSV 文件"""
    global CSV_FILE_PATH

    output_path = Path(output_dir) / "result.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    CSV_FILE_PATH = output_path

    with open(CSV_FILE_PATH, "w", newline="") as csvfile:
        fieldnames = [
            "generation",
            "individual_id",
            "fitness_type",
            "fitness",
            "mean_validation_time",
            "num_propose_set",
            "total_failures",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

    print(f"✓ CSV file initialized: {CSV_FILE_PATH}")
    return CSV_FILE_PATH

# TODO: write all evaluation results (fitness) to csv
def write_result_to_csv(result, fitness_function):
    """写入评估结果到 CSV"""
    global CSV_FILE_PATH

    if CSV_FILE_PATH is None:
        return

    with open(CSV_FILE_PATH, "a", newline="") as csvfile:
        fieldnames = [
            "generation",
            "individual_id",
            "fitness_type",
            "fitness",
            "mean_validation_time",
            "num_propose_set",
            "total_failures",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        eval_result = result["eval_result"]
        fitness_formatted = round(result["fitness"], 3)
        mean_time_formatted = (
            round(eval_result["mean_validation_time"], 3)
            if eval_result["mean_validation_time"]
            else 0.0
        )

        writer.writerow(
            {
                "generation": result["generation"],
                "individual_id": result["individual_id"],
                "fitness_type": fitness_function,
                "fitness": fitness_formatted,
                "mean_validation_time": mean_time_formatted,
                "num_propose_set": eval_result["num_propose_set"],
                "total_failures": eval_result["total_failures"],
            }
        )


def create_individual(encoding_min, encoding_max, encoding_length):
    """创建随机个体"""
    encoding = [
        random.randint(encoding_min, encoding_max) for _ in range(encoding_length)
    ]
    return creator.Individual(encoding)


def parallel_evaluate_population(
    population,
    generation,
    config,
    base_network_config,
    start_datetime,
    max_iteration,
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
    # 准备任务参数
    tasks = []
    for idx, ind in enumerate(population):
        port_offset = idx % max_workers  # 用于端口隔离
        tasks.append((
            list(ind),  # 个体基因
            generation,
            idx + 1,  # individual_id 从 1 开始
            port_offset,
            config,
            base_network_config,
            start_datetime,
            max_iteration,
            max_ledger_seq,
            seed,
            fitness_function,
            byzz_nodes,
            str(logs_dir),
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
                    write_result_to_csv(result, fitness_function)
                    
                except Exception as e:
                    print(f"Error evaluating individual: {e}")
                    import traceback
                    traceback.print_exc()
    
    return results


def main(config):
    global ENCODING_MIN, ENCODING_MAX, ENCODING_LENGTH
    global START_DATETIME, SEED, MAX_ITERATION, MAX_LEDGER_SEQ, FITNESS_FUNCTION
    global EVALUATION_COUNTER, GENERATION_DATA, CSV_FILE_PATH, MAX_PARALLEL_WORKERS
    global BYZZ_NODES

    # 重置全局变量
    GENERATION_DATA = []
    EVALUATION_COUNTER = 0
    CSV_FILE_PATH = None

    setup_interceptor(config)
    setup_docker_images(config)
    setup_deap_types()

    # 读取配置
    SEED = config.get("seed", 42)
    random.seed(SEED)
    np.random.seed(SEED)

    with open("network.yaml", "r") as f:
        base_network_config = yaml.safe_load(f)
        BYZZ_NODES = base_network_config["byzz_nodes"]

    START_DATETIME = datetime.now().strftime("%Y_%m_%d_%Hh%Mm")

    lambda_ = config.get("population_size", 4)
    mu = min(lambda_, config.get("mu", 4))
    max_generation = config.get("max_generation", 10)
    FITNESS_FUNCTION = config.get("fitness_function", "time")
    MAX_PARALLEL_WORKERS = config.get("max_parallel_workers", 4)

    ENCODING_LENGTH = NUMBER_OF_NODES * (NUMBER_OF_NODES - 1) * 7
    ENCODING_MIN = config["encoding"]["min_value"]
    ENCODING_MAX = config["encoding"]["max_value"]

    MAX_ITERATION = config.get("max_iteration", 1)
    MAX_LEDGER_SEQ = config.get("max_ledger_seq", 5)

    print(f"=== Starting Parallel (μ+λ) EA with DEAP ===")
    print(f"μ={mu}, λ={lambda_}, max_generations={max_generation}")
    print(f"Max parallel workers: {MAX_PARALLEL_WORKERS}")
    print(f"Fitness function: {FITNESS_FUNCTION}")
    print(f"Encoding length: {ENCODING_LENGTH}, range: [{ENCODING_MIN}, {ENCODING_MAX}]")
    print()

    # 初始化 CSV 文件
    output_dir = CUR_DIR / "out"
    csv_path = init_csv_file(output_dir)
    print()

    # 设置 DEAP toolbox
    toolbox = base.Toolbox()

    # 注册遗传算法操作
    toolbox.register("individual", create_individual, ENCODING_MIN, ENCODING_MAX, ENCODING_LENGTH)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)

    # 注册遗传算子
    def crossover_and_round(ind1, ind2):
        """SBX 交叉后转换为整数"""
        tools.cxSimulatedBinaryBounded(
            ind1, ind2, eta=3.0, low=ENCODING_MIN, up=ENCODING_MAX
        )
        ind1[:] = [int(round(x)) for x in ind1]
        ind2[:] = [int(round(x)) for x in ind2]
        return ind1, ind2

    def mutate_and_round(individual):
        """高斯变异后转换为整数并限制范围"""
        tools.mutGaussian(
            individual,
            mu=0,
            sigma=(ENCODING_MAX - ENCODING_MIN) / 100.0,
            indpb=1.0 / ENCODING_LENGTH,
        )
        individual[:] = [
            int(round(max(ENCODING_MIN, min(ENCODING_MAX, x)))) for x in individual
        ]
        return (individual,)

    toolbox.register("mate", crossover_and_round)
    toolbox.register("mutate", mutate_and_round)
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
        config=config,
        base_network_config=base_network_config,
        start_datetime=START_DATETIME,
        max_iteration=MAX_ITERATION,
        max_ledger_seq=MAX_LEDGER_SEQ,
        seed=SEED,
        fitness_function=FITNESS_FUNCTION,
        byzz_nodes=BYZZ_NODES,
        logs_dir=LOGS_DIR,
        max_workers=MAX_PARALLEL_WORKERS,
    )
    
    EVALUATION_COUNTER += len(results)
    
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
                config=config,
                base_network_config=base_network_config,
                start_datetime=START_DATETIME,
                max_iteration=MAX_ITERATION,
                max_ledger_seq=MAX_LEDGER_SEQ,
                seed=SEED,
                fitness_function=FITNESS_FUNCTION,
                byzz_nodes=BYZZ_NODES,
                logs_dir=LOGS_DIR,
                max_workers=MAX_PARALLEL_WORKERS,
            )
            
            EVALUATION_COUNTER += len(results)
            
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
    print(f"Total evaluations: {EVALUATION_COUNTER}")

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

    print(f"\n✓ Results saved to: {csv_path}")
    print(f"\n📊 Analysis tip:")
    print(f"   import pandas as pd")
    print(f"   df = pd.read_csv('{csv_path}')")
    print(f"   df.groupby('generation')['fitness'].describe()")

    return population, logbook, hof


if __name__ == "__main__":
    try:
        with open("evotest.yaml", "r") as f:
            config = yaml.safe_load(f)
            
            # 可以在配置中添加 max_parallel_workers
            if "max_parallel_workers" not in config:
                config["max_parallel_workers"] = 4
                
            main(config)
    except Exception as e:
        print(f"Error during evolution: {e}")
        import traceback
        traceback.print_exc()
        raise e
