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


# dirs
CUR_DIR = Path(__file__).parent
ROCKET_DIR = CUR_DIR.parent
INTERCEPTOR_DIR = ROCKET_DIR / "rocket_interceptor"
LOGS_DIR = ROCKET_DIR / "logs"

with open(CUR_DIR / "network.yaml", "r") as f:
    network_config = yaml.safe_load(f)
    NUMBER_OF_NODES = network_config["number_of_nodes"]


def gen_random_encoding(length, encoding_min, encoding_max):
    return [random.randint(encoding_min, encoding_max) for _ in range(length)]


def setup_interceptor(config):
    (CUR_DIR / "bin").mkdir(parents=True, exist_ok=True)
    ripple_image = config["ripple-image"]
    print(f"config.ripple-image = {ripple_image}, type = {type(ripple_image)}")
    # docker pull 这个image，确保本地有缓存
    print(f"Pulling docker image {ripple_image}...")
    subprocess.run(["docker", "pull", ripple_image], check=True)

    image_bin = CUR_DIR / "bin" / ripple_image.replace("/", "-")

    if not image_bin.exists():
        print(f"{image_bin} not built, building...")
        success = rebuild_interceptor_with(
            img=ripple_image, interceptor_dir=INTERCEPTOR_DIR, dest=image_bin
        )
        if not success:
            print("Rebuild interceptor failed")
            return

    assert image_bin.exists(), f"{image_bin} not exists after rebuild"

    # 将image_bin拷贝到INTERCEPTOR_DIR下以供使用
    target_path = INTERCEPTOR_DIR / "rocket-interceptor"
    shutil.copy2(image_bin, target_path)
    print(f"Copied {image_bin} to {target_path}")


def run_rocket(log_dir, max_iteration, max_ledger_seq, seed, encoding):

    os.chdir(ROCKET_DIR)
    py = sys.executable



    # 创建临时配置文件，包含 seed 和 encoding
    strategy_yaml = CUR_DIR / "EvoDelayStrategy.yaml"
    with open(strategy_yaml, "w") as f:
        yaml.dump({"seed": seed, "encoding": encoding}, f)

    cmd = [
        py,
        "-m",
        "rocket_controller",
        "EvoDelayStrategy",
        "--config",
        str(strategy_yaml),  # 使用临时配置文件
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
    # 用subprocess运行rocket_controller，实时打印输出
    # 不捕获输出，子进程直接继承父进程的 stdout/stderr（保留颜色）
    retcode = subprocess.call(cmd)

    if retcode != 0:
        print(f"Rocket exited with code {retcode}")
    else:
        print("Rocket finished successfully")

    os.chdir(CUR_DIR)


def main(config):
    setup_interceptor(config)

    seed = config.get("seed", 42)
    start_datetime = datetime.now().strftime("%Y_%m_%d_%Hh%Mm")

    max_generation = config["max_generation"]
    population_size = config["population_size"]
    # 确保generation为大于0的整数
    if not isinstance(max_generation, int) or max_generation <= 0:
        raise ValueError("max_generation must be a positive integer")

    for g in range(max_generation):
        print(f"=== Generation {g+1}/{max_generation} ===")
        
        for p in range(population_size):
            print(f"--- Individual {p+1}/{population_size} ---")
            
                # 生成随机 encoding
            encoding = gen_random_encoding(
                NUMBER_OF_NODES * (NUMBER_OF_NODES - 1) * 7,
                config["encoding"]["min_value"],
                config["encoding"]["max_value"],
            )

            print(f"Generated encoding: {encoding}")

            log_dir = f"{start_datetime}/G{g+1}T{p+1}/"

            run_rocket(
                log_dir=log_dir,
                max_iteration=1,
                max_ledger_seq=5,
                seed=seed,
                encoding=encoding,
            )

            evaluate_log(LOGS_DIR / log_dir)


if __name__ == "__main__":
    with open("evotest.yaml", "r") as f:
        config = yaml.safe_load(f)
        main(config)
