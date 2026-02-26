from pathlib import Path
import os
import sys
from cleanup import cleanup_instance_docker_containers
import yaml
import subprocess

from utils import build_interceptor, get_dirs
from datetime import datetime


repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from rocket_controller.helper import format_datetime
from evo.evaluate import evaluate_log


# 一个独立的函数，运行一个rocket实例
def run_rocket_and_evaluate(
    log_dir: Path,  # 绝对路径或相对于rocket的相对路径
    cluster_id: str,  # 生成的docker容器名称前缀，容器名为 prefix_validator_1等，这个prefix是一个cluster的唯一标识
    max_ledger_seq: int,
    seed: int,
    encoding: dict,  # 由外部生成的一个encoding字典，供controller读取
    grpc_port: int,
    rocket_dir: Path,
    tmp_dir: Path,
    byzz_min_seq: int,
    byzz_max_seq: int,
    output_screen: bool,  # 是否打印到屏幕输出
    timeout_sec_per_seq: int,
    network_yaml: Path,  # 例如，network.yaml，绝对路径
    base_port_peer: int,
    base_port_ws: int,
    base_port_ws_admin: int,
    base_port_rpc: int,
    strategy_name: str,  # 策略类名称，例如 "RandomDelayByzzPartitionStrategy"
    min_delay_ms: int,
    max_delay_ms: int,
    ripple_image: str,
    rust_log_level: str,
    fitness_function: str,
):
    cur_dir = os.getcwd()
    os.chdir(rocket_dir)
    py = sys.executable
    # 清理旧容器
    cleanup_instance_docker_containers(cluster_id)

    tmp_dir.mkdir(parents=True, exist_ok=True)

    instance_network_yaml = tmp_dir / f"network_{cluster_id}.yaml"
    # 读取network.yaml，重新配置端口号，然后输出到 instance_network_yaml
    with open(network_yaml, "r") as f:
        network_config = yaml.safe_load(f)

    (
        network_config["base_port_peer"],
        network_config["base_port_ws"],
        network_config["base_port_ws_admin"],
        network_config["base_port_rpc"],
    ) = (base_port_peer, base_port_ws, base_port_ws_admin, base_port_rpc)

    with open(instance_network_yaml, "w") as f:
        yaml.dump(network_config, f)

    # 写入strategy.yaml的配置
    strategy_yaml = tmp_dir / f"{strategy_name}_{cluster_id}.yaml"

    with open(strategy_yaml, "w") as f:
        yaml.dump(
            {
                "seed": seed,
                "encoding": encoding,
                "byzz_min_seq": byzz_min_seq,
                "byzz_max_seq": byzz_max_seq,
                "min_delay_ms": min_delay_ms,
                "max_delay_ms": max_delay_ms,
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
        str(log_dir),
        "--max-iteration",
        str(1),
        "--max-ledger-seq",
        str(max_ledger_seq),
        "--grpc-port",
        str(grpc_port),
        "--cluster-id",
        str(cluster_id),
        "--rippled-img",
        str(ripple_image),
    ]

    # 将输出重定向到 log 文件夹，或直接打印到屏幕
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_log = log_dir / "rocket_stdout.log"
    stderr_log = log_dir / "rocket_stderr.log"

    env = os.environ.copy()
    env["RUST_BACKTRACE"] = "full"
    env["RUST_LOG"] = rust_log_level

    if output_screen:
        print(
            f"[{cluster_id}] \n\tRunning command: {' '.join(cmd)}\n\toutput: (printed to screen)"
        )
        retcode = subprocess.call(cmd, env=env)
    else:
        print(
            f"[{cluster_id}] \n\tRunning command: {' '.join(cmd)}\n\tstderr saved to {log_dir / stderr_log}"
        )
        with open(stdout_log, "w") as stdout_f, open(stderr_log, "w") as stderr_f:
            retcode = subprocess.call(cmd, env=env, stdout=stdout_f, stderr=stderr_f)

    if retcode != 0:
        print(f"[{cluster_id}] Rocket exited with code {retcode}")
    else:
        print(f"[{cluster_id}] Rocket finished successfully")

    #  清理临时配置文件
    try:
        instance_network_yaml.unlink()
        strategy_yaml.unlink()
    except:
        pass

    os.chdir(cur_dir)
    
    with open(network_yaml, "r") as f:
        network_config = yaml.safe_load(f)
        byzz_nodes = network_config["byzz_nodes"]
    eval_result = evaluate_log(log_dir, byzz_nodes=byzz_nodes)
    
    if fitness_function in eval_result:
        fitness = eval_result[fitness_function] if eval_result[fitness_function] else 0.0
    else:
        fitness = 0.0
        
    return {
        "eval_result": eval_result,
        "fitness": fitness,
    }




if __name__ == "__main__":

    

    dirs = get_dirs(__file__)
    offset = 100

    build_interceptor(interceptor_dir=dirs["interceptor_dir"], cargo_clean=False)

    eval_res = run_rocket_and_evaluate(
        # ``datetime`` is already imported from ``datetime`` so use
        # ``datetime.now()`` rather than ``datetime.datetime``.
        log_dir=dirs["logs_dir"]
        / format_datetime(datetime.now())
        / "WhateverStrategy"
        / "GxTx",
        cluster_id="whatever_unique_id",
        max_ledger_seq=15,
        seed=42,
        encoding={"partition_seq": 5, "partition_duration": 1000},
        grpc_port=50051,
        rocket_dir=dirs["rocket_dir"],
        tmp_dir=dirs["tmp_dir"],
        byzz_min_seq=0,
        byzz_max_seq=10,
        output_screen=True,
        timeout_sec_per_seq=30,
        network_yaml=dirs["cur_dir"] / "network.yaml",
        base_port_peer=60000 + offset,
        base_port_ws=61000 + offset,
        base_port_ws_admin=62000 + offset,
        base_port_rpc=63000 + offset,
        strategy_name="RandomDelayByzzPartitionStrategy",
        min_delay_ms=0,
        max_delay_ms=100,
        ripple_image="xrpld:2.6.0-bug5-local",
        rust_log_level="info",
        fitness_function="num_getledger_hashes",
    )
    
    
    print(f"Evaluation result: {eval_res}")
