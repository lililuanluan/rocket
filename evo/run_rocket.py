from pathlib import Path
import os
import sys
from cleanup import cleanup_instance_docker_containers
import yaml
import subprocess
import signal

from utils import build_interceptor, get_dirs, terminate_process_group
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
    rocket_dir: Path,
    tmp_dir: Path,
    byzz_min_seq: int,
    byzz_max_seq: int,
    output_screen: bool,  # 是否打印到屏幕输出
    timeout_sec_per_seq: int,
    network_yaml: Path,  # 例如，network.yaml，绝对路径
    base_port_number: int, # 每个cluster实例占用5个端口
    strategy_name: str,  # 策略类名称，例如 "RandomDelayByzzPartitionStrategy"
    min_delay_ms: int,
    max_delay_ms: int,
    ripple_image: str,
    rust_log_level: str,
    fitness_function: str,
    individual_timeout_sec: int = 300,
):
    cur_dir = os.getcwd()
    proc: subprocess.Popen | None = None
    proc_pgid: int | None = None
    instance_network_yaml: Path | None = None
    strategy_yaml: Path | None = None
    retcode = -1
    timed_out = False
    try:
        os.chdir(rocket_dir)
        py = sys.executable

        # 清理旧容器，避免上次中断留下的同名资源冲突
        cleanup_instance_docker_containers(cluster_id)

        tmp_dir.mkdir(parents=True, exist_ok=True)
        instance_network_yaml = tmp_dir / f"network_{cluster_id}.yaml"

        # 读取network.yaml，重新配置端口号，然后输出到 instance_network_yaml
        with open(network_yaml, "r") as f:
            network_config = yaml.safe_load(f)

        # 一次运行需要占用 1+num_nodes*4 个端口，如果7个节点，则有29个端口占用
        num_nodes = network_config.get("number_of_nodes", 0) or 1
        network_config["base_port_peer"] = base_port_number
        network_config["base_port_ws"] = base_port_number + num_nodes
        network_config["base_port_ws_admin"] = base_port_number + 2 * num_nodes
        network_config["base_port_rpc"] = base_port_number + 3 * num_nodes
        # grpc port sits after all categories
        grpc_port = base_port_number + 4 * num_nodes

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
            proc = subprocess.Popen(cmd, env=env, start_new_session=True)
        else:
            print(
                f"[{cluster_id}] \n\tRunning command: {' '.join(cmd)}\n\tstderr saved to {log_dir / stderr_log}"
            )
            stdout_f = open(stdout_log, "w")
            stderr_f = open(stderr_log, "w")
            try:
                proc = subprocess.Popen(
                    cmd,
                    env=env,
                    stdout=stdout_f,
                    stderr=stderr_f,
                    start_new_session=True,
                )
            finally:
                stdout_f.close()
                stderr_f.close()

        proc_pgid = os.getpgid(proc.pid)
        try:
            retcode = proc.wait(timeout=individual_timeout_sec)
        except subprocess.TimeoutExpired:
            timed_out = True
            retcode = 124
            print(
                f"[{cluster_id}] Individual timed out after {individual_timeout_sec}s, terminating..."
            )
        except KeyboardInterrupt:
            # Let finally block do cleanup; propagate interruption to caller.
            retcode = 130
            raise

        if retcode != 0:
            print(f"[{cluster_id}] Rocket exited with code {retcode}")
        else:
            print(f"[{cluster_id}] Rocket finished successfully")
    finally:
        # Ensure the controller/interceptor subtree is not leaked on interrupt.
        # interceptor是子进程，会被清理掉
        if proc is not None and proc_pgid is not None:
            if proc.poll() is None:
                terminate_process_group(proc_pgid)
        # Cleanup all containers belonging to this cluster only.
        cleanup_instance_docker_containers(cluster_id)

        # 清理临时配置文件
        for p in (instance_network_yaml, strategy_yaml):
            if p is None:
                continue
            try:
                p.unlink()
            except Exception:
                pass

        os.chdir(cur_dir)

    # Only evaluate when run was not interrupted.
    if retcode in (130, -signal.SIGINT, -signal.SIGTERM):
        raise KeyboardInterrupt()
    if timed_out:
        return {
            "eval_result": {"timed_out": True},
            "fitness": 0.0,
        }

    with open(network_yaml, "r") as f:
        network_config = yaml.safe_load(f)
        byzz_nodes = network_config["byzz_nodes"]

    eval_result = evaluate_log(log_dir, byzz_nodes=byzz_nodes) or {}
    fitness = 0.0
    if fitness_function in eval_result:
        fitness = eval_result[fitness_function] if eval_result[fitness_function] else 0.0

    return {
        "eval_result": eval_result,
        "fitness": fitness,
    }




if __name__ == "__main__":
    # 系统端口号最大65535，不要使用 0‑1023 这些 “well‑known” 端口
    # “60000” 之所以常见只因为：大多数 Linux 发行版的 ephemeral range 是 32768‑60999， 所以 60000 以上几乎不会被内核用作临时出站端口，它在多数防火墙/路由器配置里也不是默认被拦截的。
    # 注意60000是6万，所以至少还有五千个自由端口
    dirs = get_dirs(__file__)
    
    

    build_interceptor(interceptor_dir=dirs["interceptor_dir"], cargo_clean=False)

    eval_res = run_rocket_and_evaluate(
        log_dir=dirs["logs_dir"]
        / format_datetime(datetime.now())
        / "WhateverStrategy"
        / "GxTx",
        cluster_id="whatever_unique_id",
        max_ledger_seq=15,
        seed=42,
        encoding={"partition_seq": 5, "partition_duration": 1000},
        rocket_dir=dirs["rocket_dir"],
        tmp_dir=dirs["tmp_dir"],
        byzz_min_seq=0,
        byzz_max_seq=10,
        output_screen=True,
        timeout_sec_per_seq=30,
        network_yaml=dirs["cur_dir"] / "network.yaml",
        base_port_number=60000,
        strategy_name="RandomDelayByzzPartitionStrategy",
        min_delay_ms=0,
        max_delay_ms=100,
        ripple_image="xrpld:2.6.0-bug5-local",
        rust_log_level="info",
        fitness_function="num_getledger_hashes",
        individual_timeout_sec=300,
    )
    
    
    print(f"Evaluation result: {eval_res}")
