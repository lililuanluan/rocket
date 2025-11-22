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

# DEAP imports
from deap import base, creator, tools, algorithms

# dirs
CUR_DIR = Path(__file__).parent
ROCKET_DIR = CUR_DIR.parent
INTERCEPTOR_DIR = ROCKET_DIR / "rocket_interceptor"
LOGS_DIR = ROCKET_DIR / "logs"

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

# 用于记录每代的 fitness 数据
GENERATION_DATA = []

# CSV 文件路径（用于实时写入）
CSV_FILE_PATH = None


def setup_deap_types():
    """设置 DEAP 的类型系统"""
    # 创建 FitnessMax 类（最大化fitness）
    creator.create("FitnessMax", base.Fitness, weights=(1.0,))
    # 创建 Individual 类（基于 list）
    creator.create(
        "Individual",
        list,
        fitness=creator.FitnessMax,
        log_dir=None,
        evaluation_result=None,
    )


def setup_interceptor(config):
    """设置 interceptor（与原版相同）"""
    (CUR_DIR / "bin").mkdir(parents=True, exist_ok=True)
    ripple_image = config["ripple-image"]
    print(f"config.ripple-image = {ripple_image}, type = {type(ripple_image)}")

    print(f"Pulling docker image {ripple_image}...")
    subprocess.run(["docker", "pull", ripple_image], check=True)

    image_bin = CUR_DIR / "bin" / ripple_image.replace("/", "-")

    if not image_bin.exists():
        print(f"{image_bin} not built, building...")
        success = rebuild_interceptor_with(
            img=ripple_image, interceptor_dir=INTERCEPTOR_DIR, dest=image_bin
        )
        if not success:
            raise RuntimeError("Rebuild interceptor failed")

    assert image_bin.exists(), f"{image_bin} not exists after rebuild"

    target_path = INTERCEPTOR_DIR / "rocket-interceptor"
    shutil.copy2(image_bin, target_path)
    print(f"Copied {image_bin} to {target_path}")


def run_rocket(log_dir, max_iteration, max_ledger_seq, seed, encoding):
    """运行 Rocket（与原版相同）"""
    os.chdir(ROCKET_DIR)
    py = sys.executable

    strategy_yaml = CUR_DIR / "EvoDelayStrategy.yaml"
    with open(strategy_yaml, "w") as f:
        yaml.dump({"seed": seed, "encoding": encoding}, f)

    cmd = [
        py,
        "-m",
        "rocket_controller",
        "EvoDelayStrategy",
        "--config",
        str(strategy_yaml),
        "--network_config",
        str(CUR_DIR / "network.yaml"),
        "--log-dir",
        log_dir,
        "--max-iteration",
        str(max_iteration),
        "--max-ledger-seq",
        str(max_ledger_seq),
    ]

    print(f"running command: {' '.join(cmd)}")
    retcode = subprocess.call(cmd)

    if retcode != 0:
        print(f"Rocket exited with code {retcode}")
    else:
        print("Rocket finished successfully")

    os.chdir(CUR_DIR)


def evaluate_individual(individual, generation, individual_id):
    """
    评估函数 - DEAP 要求返回 tuple
    这是 DEAP 与手工实现的主要接口
    """
    global EVALUATION_COUNTER
    EVALUATION_COUNTER += 1

    # 生成 log 目录 - 使用 G{generation}T{individual_id} 格式
    log_dir = f"{START_DATETIME}/G{generation}T{individual_id}/"

    # 运行 Rocket
    run_rocket(log_dir, MAX_ITERATION, MAX_LEDGER_SEQ, SEED, list(individual))

    # 评估结果
    eval_result = evaluate_log(LOGS_DIR / log_dir)

    # 保存到 individual 对象上
    individual.log_dir = log_dir
    individual.evaluation_result = eval_result

    # 计算 fitness（DEAP 要求返回 tuple）
    if FITNESS_FUNCTION == "time":
        fitness = (
            eval_result["mean_validation_time"]
            if eval_result["mean_validation_time"]
            else 0.0
        )
    elif FITNESS_FUNCTION == "proposal":
        fitness = (
            eval_result["propose_set_count"]
            if eval_result["propose_set_count"]
            else 0.0
        )
    else:
        fitness = 0.0

    print(f"Individual fitness: {fitness}")

    # 实时写入 CSV（传递完整的 eval_result）
    write_individual_to_csv(generation, individual_id, fitness, eval_result)

    return (fitness,)  # DEAP 要求返回 tuple!


def create_individual():
    """创建随机个体的工厂函数"""
    encoding = [
        random.randint(ENCODING_MIN, ENCODING_MAX) for _ in range(ENCODING_LENGTH)
    ]
    return creator.Individual(encoding)


def init_csv_file(output_dir):
    """初始化 CSV 文件，写入表头"""
    global CSV_FILE_PATH

    output_path = Path(output_dir) / "result.csv"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    CSV_FILE_PATH = output_path

    # 写入表头
    with open(CSV_FILE_PATH, "w", newline="") as csvfile:
        fieldnames = [
            "generation",
            "individual_id",
            "fitness_type",
            "fitness",
            "mean_validation_time",
            "propose_set_count",
            "total_failures",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

    print(f"✓ CSV file initialized: {CSV_FILE_PATH}")
    return CSV_FILE_PATH


def write_individual_to_csv(generation, individual_id, fitness, eval_result):
    """实时写入单个个体的结果到 CSV"""
    global CSV_FILE_PATH, FITNESS_FUNCTION

    if CSV_FILE_PATH is None:
        print("Warning: CSV file not initialized!")
        return

    # 追加写入
    with open(CSV_FILE_PATH, "a", newline="") as csvfile:
        fieldnames = [
            "generation",
            "individual_id",
            "fitness_type",
            "fitness",
            "mean_validation_time",
            "propose_set_count",
            "total_failures",
        ]
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

        # 格式化浮点数为三位小数
        fitness_formatted = round(fitness, 3)
        mean_time_formatted = (
            round(eval_result["mean_validation_time"], 3)
            if eval_result["mean_validation_time"]
            else 0.0
        )

        writer.writerow(
            {
                "generation": generation,
                "individual_id": individual_id,
                "fitness_type": FITNESS_FUNCTION,  # 'time' or 'proposal'
                "fitness": fitness_formatted,
                "mean_validation_time": mean_time_formatted,
                "propose_set_count": eval_result["propose_set_count"],
                "total_failures": eval_result["total_failures"],
            }
        )

    print(
        f"  ✓ Written to CSV: G{generation}T{individual_id}, fitness={fitness_formatted:.3f}"
    )


def main(config):
    global ENCODING_MIN, ENCODING_MAX, ENCODING_LENGTH
    global START_DATETIME, SEED, MAX_ITERATION, MAX_LEDGER_SEQ, FITNESS_FUNCTION
    global EVALUATION_COUNTER, GENERATION_DATA, CSV_FILE_PATH

    # 重置全局变量
    GENERATION_DATA = []
    EVALUATION_COUNTER = 0
    CSV_FILE_PATH = None

    setup_interceptor(config)
    setup_deap_types()

    # 读取配置
    SEED = config.get("seed", 42)
    random.seed(SEED)
    np.random.seed(SEED)

    START_DATETIME = datetime.now().strftime("%Y_%m_%d_%Hh%Mm")

    
    lambda_ = config.get("population_size", 4)
    mu = min(lambda_, config.get("mu", 4))
    max_generation = config.get("max_generation", 10)
    FITNESS_FUNCTION = config.get("fitness_function", "time")

    ENCODING_LENGTH = NUMBER_OF_NODES * (NUMBER_OF_NODES - 1) * 7
    ENCODING_MIN = config["encoding"]["min_value"]
    ENCODING_MAX = config["encoding"]["max_value"]

    MAX_ITERATION = config.get("max_iteration", 1)
    MAX_LEDGER_SEQ = config.get("max_ledger_seq", 5)

    print(f"=== Starting (μ+λ) EA with DEAP ===")
    print(f"μ={mu}, λ={lambda_}, max_generations={max_generation}")
    print(f"Fitness function: {FITNESS_FUNCTION}")
    print(
        f"Encoding length: {ENCODING_LENGTH}, range: [{ENCODING_MIN}, {ENCODING_MAX}]"
    )
    print()

    # 初始化 CSV 文件
    output_dir = CUR_DIR / "out"
    csv_path = init_csv_file(output_dir)
    print()

    # 设置 DEAP toolbox
    toolbox = base.Toolbox()

    # 注册遗传算法操作
    toolbox.register("individual", create_individual)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)
    # 注意：不再注册 evaluate，因为我们需要传递额外参数

    # 注册遗传算子
    # SBX crossover with eta=3
    def crossover_and_round(ind1, ind2):
        """SBX 交叉后转换为整数"""
        tools.cxSimulatedBinaryBounded(
            ind1, ind2, eta=3.0, low=ENCODING_MIN, up=ENCODING_MAX
        )
        # 转换为整数
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
        # 转换为整数并限制在 [ENCODING_MIN, ENCODING_MAX] 范围内
        individual[:] = [
            int(round(max(ENCODING_MIN, min(ENCODING_MAX, x)))) for x in individual
        ]
        return (individual,)

    toolbox.register("mate", crossover_and_round)
    toolbox.register("mutate", mutate_and_round)

    # Selection: tournament or best
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

    print(f"=== Initialization ===")
    # 初始化种群
    population = toolbox.population(n=lambda_)

    # 评估初始种群 (Generation 0)
    for idx, ind in enumerate(population):
        fitness = evaluate_individual(ind, generation=0, individual_id=idx + 1)
        ind.fitness.values = fitness

    # 更新 HallOfFame 和统计
    hof.update(population)
    record = stats.compile(population)
    logbook.record(gen=0, nevals=len(population), **record)
    print(logbook.stream)

    # 选择 mu 个父代
    population = toolbox.select(population, mu)

    # 主进化循环
    for gen in range(1, max_generation + 1):
        # 生成子代
        offspring = algorithms.varOr(population, toolbox, lambda_, cxpb=0.7, mutpb=0.3)

        # 评估子代中未评估的个体
        invalid_ind = [ind for ind in offspring if not ind.fitness.valid]
        for idx, ind in enumerate(invalid_ind):
            fitness = evaluate_individual(ind, generation=gen, individual_id=idx + 1)
            ind.fitness.values = fitness

        # (μ+λ) 选择：从父代+子代中选择最佳的 mu 个
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
    print(
        f"  Log directory: {best_ind.log_dir if hasattr(best_ind, 'log_dir') else 'N/A'}"
    )
    print(f"  Encoding (first 10 genes): {list(best_ind)[:10]}...")

    if hasattr(best_ind, "evaluation_result") and best_ind.evaluation_result:
        result = best_ind.evaluation_result
        # evaluate_log returns a dict; use key access to avoid AttributeError
        print(f"  Mean validation time: {result.get('mean_validation_time')}")
        print(f"  Propose set count: {result.get('propose_set_count')}")
        print(f"  Total failures: {result.get('total_failures')}")

    # 打印进化日志
    print("\n=== Evolution Statistics ===")
    print(logbook)

    # CSV 已经实时写入，只需提示位置
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
            main(config)
    except Exception as e:
        print(f"Error during evolution: {e}")
        raise e
    
