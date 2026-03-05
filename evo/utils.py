import os
from pathlib import Path
import subprocess
import json
import re


def get_last_log_dir():
    # 获取 __file__/../logs/ 目录下最新的日志文件夹

    log_dir = Path(__file__).resolve().parent.parent / "logs"
    if not log_dir.exists():
        raise FileNotFoundError(f"log {log_dir} does not exist.")

    # 返回最新的日志文件夹
    return max(log_dir.iterdir(), key=os.path.getmtime)


def get_dirs(script_path) -> dict: 
    # dir: 文件夹
    # path：文件或文件夹
    # must be some script in rocket/evo/
    cur_dir = Path(script_path).parent
    rocket_dir = cur_dir.parent
    interceptor_dir = rocket_dir / "rocket_interceptor"
    logs_dir = rocket_dir / "logs"
    tmp_dir = cur_dir / "tmp"
    return {
        "cur_dir": cur_dir,
        "rocket_dir": rocket_dir,
        "interceptor_dir": interceptor_dir,
        "logs_dir": logs_dir,
        "tmp_dir": tmp_dir,
    }

def build_interceptor(interceptor_dir, cargo_clean=False):
    """设置 interceptor"""
    original_cwd = os.getcwd()
    os.chdir(interceptor_dir)
    try:
        if cargo_clean:
            subprocess.run(["cargo", "clean"], check=True)
        subprocess.run(["./build.sh"], check=True)
    except Exception as e:
        print(f"Error occurred while building interceptor: {e}")
        raise RuntimeError("Rebuild interceptor failed")
    finally:
        os.chdir(original_cwd)



    target_path = interceptor_dir / "rocket-interceptor"
    assert target_path.exists(), f"Interceptor binary not found at {target_path}"



def setup_docker_images(ripple_image, rocket_dir):
    # 打印当前本地所有的docker镜像
    """拉取/构建 Docker 镜像"""
    if "local" not in ripple_image:
        print(f"Pulling Docker image: {ripple_image}")
        subprocess.run(["docker", "pull", ripple_image], check=True)

    original_cwd = os.getcwd()
    os.chdir(rocket_dir / "images")
    # 去掉ripple_image中前面 "xrpld:" 的部分
    build_target = ripple_image.split(":")[-1]
    if "local" in ripple_image:
        print(f"Building local Docker image: {ripple_image} with target {build_target}")
        # use the new setup.py helper in images/ to build, which handles
        # dockerfile generation, parallelism and caching control
        cmd = ["python3", "setup.py", "--build", build_target]

        # first attempt, retry once with no-cache on failure
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError:
            print("Initial build failed, retrying with --no-cache flag...")
            retry_cmd = cmd + ["-f"]
            subprocess.run(retry_cmd, check=True)
        print("✓ Local images built successfully (via setup.py)")
    os.chdir(original_cwd)


def get_strategy_name(strategy):

    # 检查策略类是否在 rocket_controller/strategies 中存在
    import importlib
    strategies_module = importlib.import_module("rocket_controller.strategies")
    if not hasattr(strategies_module, strategy):
        raise ValueError(
            f"Strategy class '{strategy}' not found in rocket_controller/strategies. "
            f"Available: {[c for c in dir(strategies_module) if not c.startswith('_')]}"
        )

    return strategy


def sanitize_cluster_id(s: str) -> str:
    """Return a string safe to use as a Docker container prefix.

    Docker only permits names matching ``[A-Za-z0-9][A-Za-z0-9_.-]+``;
    any other character (including path separators or spaces) will cause
    the daemon to reject the name with a ``400`` error.  This helper
    replaces all invalid characters with underscores and ensures the
    result starts with an alphanumeric character by prepending ``c`` if
    necessary.

    The normalization is intentionally conservative: we don't attempt to
    preserve interesting parts of long paths, only to guarantee a valid
    identifier that is still human‑readable.
    """

    # replace anything not in the allowed character set with '_'
    sanitized = re.sub(r"[^A-Za-z0-9_.-]", "_", s)

    if not sanitized:
        return "c"
    if not sanitized[0].isalnum():
        sanitized = "c" + sanitized
    return sanitized


def make_cluster_id(logs_dir: str, test_log_dir: str, individual_id: str) -> str:
    """Generate a unique, docker-safe cluster ID for an evaluation.

    The previous approach simply used the individual identifier (e.g.
    ``G0T1``), which worked when only one test ran at a time.  When
    ``run_evotests.py`` launches several configurations in parallel the
    same individual IDs recur and different processes attempt to create
    containers with identical names, causing ``409 Conflict`` errors.

    To avoid this we include a short representation of the ``test_log_dir``
    (relative to ``logs_dir`` if possible) in the cluster ID.  This
    ensures that distinct configurations always produce distinct IDs while
    keeping names reasonably short.  The resulting string is then fed
    through :func:`sanitize_cluster_id` to remove any remaining invalid
    characters.
    """

    logs_path = Path(logs_dir)
    test_path = Path(test_log_dir)
    try:
        rel = test_path.relative_to(logs_path)
    except Exception:
        rel = test_path

    prefix = "_".join(rel.parts)
    raw = f"{prefix}_{individual_id}" if prefix else individual_id
    return sanitize_cluster_id(raw)


def aggregate_logs(log_dir=None):
    if log_dir is None:
        log_dir = get_last_log_dir()

    # 获取log_dir下所有子文件夹，获取G{g}T{t}中的g t，然后根据g，t的字典序排序，打印所有子文件夹的名称
    sub_dirs = [d for d in log_dir.iterdir() if d.is_dir()]
    sub_dirs.sort(
        key=lambda d: (
            int(d.name.split("G")[1].split("T")[0]),
            int(d.name.split("T")[1]),
        )
    )
    for sub_dir in sub_dirs:
        line = sub_dir.name
        # 获取sub_dir/aggregated_spec_check_log.json，如果存在则加载到json对象中，读取"correct_runs"字段
        spec_check_log_path = sub_dir / "aggregated_spec_check_log.json"
        if spec_check_log_path.exists():
            with open(spec_check_log_path, "r") as f:
                spec_check_log = json.load(f)
                correct_runs = spec_check_log["correct_runs"]
                line += f" correct_runs: {correct_runs}"

        # 读取 fitness.json，获取 fitness 函数名及对应值 (fitness.json还没有实现)
        fitness_json_path = sub_dir / "fitness.json"
        if fitness_json_path.exists():
            with open(fitness_json_path, "r") as f:
                fitness_data = json.load(f)
                fitness_func = (
                    fitness_data.get("fitness", "mean_validation_time")
                    or "mean_validation_time"
                )
                fitness_value = fitness_data.get(fitness_func)
                if fitness_value is not None:
                    line += f" {fitness_func}: {round(fitness_value, 4)}"
                else:
                    line += f" {fitness_func}: N/A"

        print(line)


if __name__ == "__main__":
    aggregate_logs()
