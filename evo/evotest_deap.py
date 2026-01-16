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
import docker
from pathlib import Path

# DEAP imports
from deap import base, creator, tools, algorithms

# dirs
CUR_DIR = Path(__file__).parent
ROCKET_DIR = CUR_DIR.parent
INTERCEPTOR_DIR = ROCKET_DIR / "rocket_interceptor"
LOGS_DIR = ROCKET_DIR / "logs"
# network config path used at runtime (can be rewritten with adjusted ports)
NETWORK_CONFIG_PATH = CUR_DIR / "network.yaml"

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


def setup_local_images():
    """使用 make 自动检测 Dockerfile/rippled 变更并构建镜像"""
    original_cwd = os.getcwd()
    os.chdir(ROCKET_DIR / "images")
    try:
        # 使用 Popen 实现实时输出 + 错误检查
        process = subprocess.Popen(
            ["make", "build"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # 将stderr合并到stdout
            text=True,
            bufsize=1,
        )
        
        # 实时读取并打印输出
        output_lines = []
        for line in process.stdout:
            print(line, end='')  # 实时打印
            output_lines.append(line)
        
        # 等待进程结束
        return_code = process.wait()
        
        if return_code != 0:
            # 如果失败，可以重新打印所有输出或提取关键信息
            print("\n=== Build failed with output ===")
            print(''.join(output_lines[-20:]))  # 打印最后20行
            raise RuntimeError("Make build failed")
            
    except Exception as e:
        print(f"Warning: Could not setup local images: {e}")
        raise RuntimeError("Local docker images setup failed")
    finally:
        print("docker image built.")
        os.chdir(original_cwd)


def cleanup_docker_containers():
    """停止所有 validator 容器（包含已退出的容器）。"""
    try:
        print("\n🧹 Cleaning up Docker validator containers...")
        docker_client = docker.from_env()
        # all=True 以包含已退出的容器，避免命名冲突（如 key_generator 已退出但仍占用名字）
        for c in docker_client.containers.list(all=True):
            name = c.name
            if "validator_" in name or name == "key_generator":
                print(f"Stopping/removing container: {name}")
                try:
                    c.stop(timeout=3)
                except Exception:
                    # 容器可能已退出，忽略 stop 错误
                    pass
                # 强制删除，确保名字被释放
                c.remove(force=True)
        print("✓ Docker cleanup complete")
    except Exception as e:
        print(f"Warning: Could not cleanup Docker containers: {e}")


def ensure_ports_free(
    base_peer: int, base_ws: int, base_ws_admin: int, base_rpc: int, n: int
):
    """检查端口占用，如果有占用则尝试清理相关容器后再检查一次。"""
    docker_client = docker.from_env()

    def _ports_in_use() -> list[int]:
        ports = set()
        for i in range(n):
            ports.update(
                {
                    base_peer + i,
                    base_ws + i,
                    base_ws_admin + i,
                    base_rpc + i,
                }
            )
        in_use = []
        for p in sorted(ports):
            if not socket_available(p):
                in_use.append(p)
        return in_use

    def _kill_conflicting_containers():
        try:
            for c in docker_client.containers.list(all=True):
                # 尝试匹配 validator_/key_generator，或端口绑定命中目标端口
                name = c.name
                binds_target = False
                try:
                    inspect = c.attrs
                    host_config = inspect.get("HostConfig", {})
                    port_bindings = host_config.get("PortBindings", {})
                    for bindings in port_bindings.values():
                        for b in bindings:
                            hp = b.get("HostPort")
                            if hp and hp.isdigit() and int(hp) in _ports_in_use():
                                binds_target = True
                                break
                        if binds_target:
                            break
                except Exception:
                    pass

                if "validator_" in name or name == "key_generator" or binds_target:
                    print(f"🔪 Removing container occupying target ports: {name}")
                    try:
                        c.stop(timeout=3)
                    except Exception:
                        pass
                    try:
                        c.remove(force=True)
                    except Exception as e:
                        print(f"Warning: failed to remove {name}: {e}")
        except Exception as e:
            print(f"Warning: failed to inspect containers for port conflicts: {e}")

    first_conflicts = _ports_in_use()
    if first_conflicts:
        print(f"⚠️  Ports in use before start: {first_conflicts}, trying to clean up...")
        _kill_conflicting_containers()
        second_conflicts = _ports_in_use()
        if second_conflicts:
            print(
                "⚠️  Ports still in use after cleanup: {0}. Will switch to an alternate base port block.".format(
                    second_conflicts
                )
            )
            return False
    else:
        print("✓ All required ports are available.")
        # input()
    return True


def socket_available(port: int, host: str = "0.0.0.0") -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def cleanup_interceptor_processes():
    """清理所有 rocket-interceptor 进程"""
    try:
        print("\n🧹 Cleaning up rocket-interceptor processes...")
        subprocess.run(
            ["killall", "-9", "rocket-interceptor"],
            stderr=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
        )
        print("✓ Cleanup complete")
    except Exception as e:
        print(f"Warning: Could not cleanup processes: {e}")


def cleanup_fs():
    # 自动清理脏数据，防止 rippled state db error
    config_db = ROCKET_DIR / "rocket_interceptor" / "network" / "key_generator" / "config" / "db"
    varlib_db = ROCKET_DIR / "rocket_interceptor" / "network" / "key_generator" / "var" / "lib" / "rippled" / "db"
    # 清理 /config/db/state* 文件
    try:
        print("\n🧹 Cleaning up interceptor filesystem state...")
        if config_db.exists():
            for f in config_db.glob("state*"):
                f.unlink()
        # 清理 /var/lib/rippled/db/*
        if varlib_db.exists():
            for f in varlib_db.iterdir():
                if f.is_file():
                    f.unlink()
                elif f.is_dir():
                    shutil.rmtree(f)
                    input(f"Warning: Could not delete {f}")
                    pass
    except Exception as e:
        print(f"Warning: Could not cleanup filesystem: {e}")
    finally:
        print("✓ Filesystem cleanup complete")

def cleanup_all():
    """清理所有资源"""
    cleanup_docker_containers()
    cleanup_interceptor_processes()
    cleanup_fs()







def docker_image_exists(image: str) -> bool:
    """Check if a docker image exists locally."""
    res = subprocess.run(
        ["docker", "image", "inspect", image],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return res.returncode == 0


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
    # If using rippled 1.4.0, run a compatibility fix on configs before building
    try:
        maybe_fix_configs_for_1_4(ripple_image)
    except Exception as e:
        print(f"Warning: config fix step failed: {e}")
    print(f"config.ripple-image = {ripple_image}, type = {type(ripple_image)}")

    if docker_image_exists(ripple_image):
        print(f"Docker image {ripple_image} already present locally, skip pull")
    else:
        print(f"Pulling docker image {ripple_image}...")
        subprocess.run(["docker", "pull", ripple_image], check=True)

    image_bin = INTERCEPTOR_DIR / "rocket-interceptor"

    success = rebuild_interceptor_with(
        img=ripple_image, interceptor_dir=INTERCEPTOR_DIR
    )

    if not success:
        raise RuntimeError("Rebuild interceptor failed")

    assert image_bin.exists(), f"{image_bin} not exists after rebuild"


def preflight_create_validator_config_dirs(n_nodes: int):
    """Ensure that network/validators/<validator_i>/config directories exist and are
    owned/created by the current user so Docker won't auto-create them as root.
    This function intentionally does NOT chown existing files; it only creates missing
    directories and placeholder files where safe.
    """
    print(f"Preflight: ensuring validator config dirs exist for {n_nodes} nodes...")
    base = INTERCEPTOR_DIR / "network" / "validators"
    base.mkdir(parents=True, exist_ok=True)
    for i in range(n_nodes):
        cfg_dir = base / f"validator_{i}" / "config"
        if not cfg_dir.exists():
            print(f"Creating config dir for validator_{i}: {cfg_dir}")
            cfg_dir.mkdir(parents=True, exist_ok=True)
        # Create lightweight placeholder files to avoid empty-mount surprises.
        rippled_cfg = cfg_dir / "rippled.cfg"
        if not rippled_cfg.exists():
            # write a minimal placeholder that will be overwritten by the interceptor
            rippled_cfg.write_text("# placeholder rippled.cfg\n")
        ledger_json = cfg_dir / "ledger.json"
        if not ledger_json.exists():
            ledger_json.write_text("{}\n")
        validators_txt = cfg_dir / "validators.txt"
        if not validators_txt.exists():
            validators_txt.write_text("[validators]\n")


def maybe_fix_configs_for_1_4(ripple_image):
    """If the provided ripple_image indicates rippled 1.4.0, run the
    compatibility fixer script to normalize validator configs for v1.4.0.

    This is intentionally conservative: only triggers when the image tag
    contains the literal '1.4.0'.
    """
    try:
        img = str(ripple_image)
    except Exception:
        img = ripple_image
    scripts_dir = Path(__file__).resolve().parents[1] / "scripts"
    preflight = scripts_dir / "preflight_rippled_cfg.py"
    fixer = scripts_dir / "fix_rippled_cfgs.py"

    # Always run the preflight check first (report-only). This detects problems
    # for any rippled version without changing files.
    if preflight.exists():
        print(f"Running rippled preflight check: {preflight}")
        try:
            res = subprocess.run([sys.executable, str(preflight)], check=False)
            print(f"Preflight exit code: {res.returncode}")
        except Exception as e:
            print(f"Warning: failed to run preflight {preflight}: {e}")
    else:
        print(f"Preflight script not found at {preflight}; skipping preflight")

    # Decide whether to run the in-place fixer. We want to be proactive for any
    # 1.4.x image (contains "1.4") or when the operator explicitly requests it via
    # FORCE_CONFIG_FIXER=1/true. The fixer creates .bak backups of modified files.
    force_fixer = os.environ.get("FORCE_CONFIG_FIXER", "0").lower() in ("1", "true")
    if "1.4" in img or force_fixer:
        why = []
        if "1.4" in img:
            why.append("image indicates 1.4.x")
        if force_fixer:
            why.append("FORCE_CONFIG_FIXER set")
        print(f"Detected rippled image {img} ({', '.join(why)}): running config fixer...")
        if fixer.exists():
            try:
                res_fix = subprocess.run([sys.executable, str(fixer)], check=False)
                print(f"Fixer exit code: {res_fix.returncode}")
            except Exception as e:
                print(f"Warning: failed to run fixer {fixer}: {e}")

            # Re-run preflight to validate the fix (best-effort)
            if preflight.exists():
                try:
                    res2 = subprocess.run([sys.executable, str(preflight)], check=False)
                    print(f"Post-fix preflight exit code: {res2.returncode}")
                except Exception as e:
                    print(f"Warning: failed to re-run preflight {preflight}: {e}")
        else:
            print(f"Config fixer not found at {fixer}; skipping fix step")
    else:
        print(f"rippled image {img} does not appear to be 1.4.x and FORCE_CONFIG_FIXER not set; skipping config fixer")


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
        str(NETWORK_CONFIG_PATH),
        "--log-dir",
        log_dir,
        "--max-iteration",
        str(max_iteration),
        "--max-ledger-seq",
        str(max_ledger_seq),
    ]

    print(f"running command: {' '.join(cmd)}")
    env = os.environ.copy()
    env['RUST_BACKTRACE'] = '1'
    retcode = subprocess.call(cmd, env=env)

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

    cleanup_all()

    

    setup_local_images()
    # 在启动前确保端口未被占用（包含遗留容器占用），否则自动切换到备用端口段
    base_peer = network_config["base_port_peer"]
    base_ws = network_config["base_port_ws"]
    base_ws_admin = network_config["base_port_ws_admin"]
    base_rpc = network_config["base_port_rpc"]

    ok = ensure_ports_free(
        base_peer=base_peer,
        base_ws=base_ws,
        base_ws_admin=base_ws_admin,
        base_rpc=base_rpc,
        n=NUMBER_OF_NODES,
    )

    # 如果端口冲突或使用了默认被占用的段，尝试一系列候选端口段，直到找到可用的
    if not ok:# or base_peer == 60000:
        # candidates = [
        #     (50000, 51000, 52000, 53000),
        #     (54000, 55000, 56000, 57000),
        #     (58000, 59000, 60000, 61000),
        # ]
        # chosen = None
        # for bp, bws, bwsadm, brpc in candidates:
        #     print(f"🔀 Trying port block: {bp}/{bws}/{bwsadm}/{brpc}")
        #     if ensure_ports_free(
        #         base_peer=bp,
        #         base_ws=bws,
        #         base_ws_admin=bwsadm,
        #         base_rpc=brpc,
        #         n=NUMBER_OF_NODES,
        #     ):
        #         chosen = (bp, bws, bwsadm, brpc)
        #         break

        # if chosen is None:
        #     raise RuntimeError(
        #         "Ports are still in use or unavailable; please free them or adjust base ports manually."
        #     )
        # else:
        #     base_peer, base_ws, base_ws_admin, base_rpc = chosen
        #     print(f"🔀 Selected port block: {base_peer}/{base_ws}/{base_ws_admin}/{base_rpc}")
        raise RuntimeError("Failed to find available port block.")

    # 用运行时覆盖 network_config 中的端口（不改文件）
    network_config["base_port_peer"] = base_peer
    network_config["base_port_ws"] = base_ws
    network_config["base_port_ws_admin"] = base_ws_admin
    network_config["base_port_rpc"] = base_rpc

    # 将运行时配置写到单独文件供 rocket_controller 使用，避免修改原 network.yaml
    global NETWORK_CONFIG_PATH
    runtime_network = CUR_DIR / "network.runtime.yaml"
    with open(runtime_network, "w") as f:
        yaml.safe_dump(network_config, f, sort_keys=False)
    NETWORK_CONFIG_PATH = runtime_network
    # Ensure validator config directories exist and are created by this user
    preflight_create_validator_config_dirs(NUMBER_OF_NODES)
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
    except KeyboardInterrupt:
                cleanup_all()
                sys.exit(130)
    except Exception as e:
        print(f"Error during evolution: {e}")
        raise e
