import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
import yaml
from utils import get_dirs, get_date_time_strf
import os
import signal
import time


procs = []


def signal_handler(sig, frame):
    print("Received signal", sig, "terminating children...")
    for p in procs:
        if p.poll() is None:
            # 还没结束
            try:
                os.killpg(p.pid, signal.SIGTERM)  # 杀死整个进程组 process group
            except Exception as e:
                print("[SIGTERM] Error killing process", p.pid, ":", e)
    time.sleep(2)  # 等待子进程清理完
    # 如果仍然存活，强制杀死
    for p in procs:
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except Exception as e:
                print("[SIGKILL] Error killing process", p.pid, ":", e)
    sys.exit(130)


def main():
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    dirs = get_dirs(__file__)
    images = [
        f"xrpld:2.6.0-bug{i}-local" for i in range(11, 16)
    ]  # "xrpllabsofficial/xrpld:2.6.0", "xrpllabsofficial/xrpld:3.1.0"
    strategies = [
        "EvoDelayByzzPartitionStrategy",
        # "RandomDelayByzzPartitionStrategy",
    ]  # "RandomDelayByzzPartitionStrategy"
    # choose real fitness names from the allowed list; "fitness_function" was
    # a placeholder and not a valid choice for the CLI parser
    fitnesses = [
        "mean_validation_time",
        # "num_getledger_messages",
        # "message_entropy_integral",
        # "markov_matrix_non_similarity",
        # "var_validation_time",
    ]  #  "num_getledger_messages"

    log_dir = Path(dirs["logs_dir"]) / get_date_time_strf()
    # 创建日志目录
    log_dir.mkdir(parents=True, exist_ok=True)

    idx = 0
    port_start = 60000
    network_yaml = Path(dirs["cur_dir"]) / "network.yaml"
    max_num_nodes = 10
    try:
        with open(network_yaml, "r") as f:
            network_cfg = yaml.safe_load(f) or {}
        max_num_nodes = int(network_cfg.get("number_of_nodes", max_num_nodes))
    except Exception:
        print(
            f"Warning: failed to read {network_yaml}, "
            f"fallback to max_num_nodes={max_num_nodes}"
        )
    population_size = 10
    # 关于端口：每个测试需要占用 1+num_nodes*4，所以最多有 1+10*4=41 个端口占用。
    # 每个population要运行 population_size 个测试，所以每个population需要 41*population_size=410 个端口。
    # 多个generation之前串行，所以不影响
    population_port_range = (1 + max_num_nodes * 4) * population_size

    for j, strategy in enumerate(strategies):
        for k, fitness in enumerate(fitnesses):
            for i, img in enumerate(images):

                logs_group_dir = f"{log_dir}/{img.replace(':','_').replace('/', '_')}/{strategy}/{fitness}"

                # 计算端口起始位置
                base_port_population = port_start + idx * population_port_range

                # run_evotest_parallel接受 a logs_group_dir argument which the
                # child will treat as *the* directory for this configuration.
                # It no longer appends the strategy name itself, so callers
                # (including this helper script) are responsible for any
                # grouping they require.  We already include image/strategy/
                # fitness in our constructed path.

                cmd = [
                    sys.executable,
                    "-m",
                    "evo.evotest_parallel",
                    "--logs-group-dir",
                    logs_group_dir,
                    "--ripple-image",
                    img,
                    "--strategy",
                    strategy,
                    "--fitness-function",
                    fitness,
                    "--base-port-population",
                    str(base_port_population),
                    "--max-parallel-workers",
                    str(5),
                    "--total-num-tests",
                    str(500),
                    "--population-size",
                    str(population_size),
                    "--individual-timeout-sec",
                    str(180),
                ]

                print("Starting", " ".join(cmd))
                # copy parent's environment and ensure the workspace root is
                # on PYTHONPATH so that ``-m evo.evotest_parallel`` can be
                # imported even when run from a different cwd.  derive the
                # root from the location of this script rather than hardcoding
                # a path.
                env = subprocess.os.environ.copy()
                root = Path(__file__).resolve().parent.parent
                existing = env.get("PYTHONPATH", "")
                env["PYTHONPATH"] = str(root) + (":" + existing if existing else "")
                proc = subprocess.Popen(cmd, env=env, start_new_session=True)
                procs.append(proc)
                idx += 1
                proc.wait()

    # wait for all children to exit
    # for p in procs:
    #     p.wait()


if __name__ == "__main__":
    import sys
    from pathlib import Path

    main()
