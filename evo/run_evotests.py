import subprocess
import sys
import time
from pathlib import Path
import yaml
from utils import get_dirs, get_date_time_strf
import os
import signal


procs = []


def normalize_strategy_combo(entry) -> dict:
    """Normalize a strategy config entry into a composed-mode triple."""
    if isinstance(entry, dict):
        delay_mode = entry.get("delay_mode")
        partition_mode = entry.get("partition_mode")
        byzz_mode = entry.get("byzz_mode")
    elif isinstance(entry, (list, tuple)) and len(entry) == 3:
        delay_mode, partition_mode, byzz_mode = entry
    else:
        raise ValueError(
            "Each strategies entry must be either a dict with "
            "{delay_mode, partition_mode, byzz_mode} or a 3-item list/tuple."
        )

    combo = {
        "delay_mode": delay_mode,
        "partition_mode": partition_mode,
        "byzz_mode": byzz_mode,
    }
    missing = [k for k, v in combo.items() if not v]
    if missing:
        raise ValueError(f"Strategy mode combo is missing values for: {missing}")
    return combo


def format_strategy_combo(combo: dict) -> str:
    return (
        f"delay-{combo['delay_mode']}__"
        f"partition-{combo['partition_mode']}__"
        f"byzz-{combo['byzz_mode']}"
    )


def load_config(config_file: Path) -> dict:
    """Load and return configuration from a YAML file."""
    if not config_file.exists():
        raise FileNotFoundError(f"Config file not found: {config_file}")
    with open(config_file, "r") as f:
        return yaml.safe_load(f) or {}


def validate_config(config: dict):
    """Raise ValueError if any required keys are missing or have wrong types."""
    required = [
        "ripple_images",
        "strategies",
        "fitness_functions",
        "max_parallel_workers",
        "individual_timeout_sec",
    ]
    missing = [k for k in required if not config.get(k)]
    if missing:
        raise ValueError(f"Missing required config keys: {missing}")
    for key in ["ripple_images", "strategies", "fitness_functions"]:
        if not isinstance(config[key], list):
            raise ValueError(f"Config key '{key}' must be a list")
    for entry in config["strategies"]:
        normalize_strategy_combo(entry)

    for key in [
        "max_parallel_workers",
        "individual_timeout_sec",
        "population_size",
        "total_num_tests",
        "partition_seq",
        "partition_duration",
        "max_partition_duration",
    ]:
        if key in config and config[key] is not None and (
            not isinstance(config[key], int) or config[key] <= 0
        ):
            raise ValueError(f"Config key '{key}' must be a positive integer")

    if "mu" in config and (not isinstance(config["mu"], int) or config["mu"] <= 0):
        raise ValueError("Config key 'mu' must be a positive integer")

    if "runtime_retries" in config and (
        not isinstance(config["runtime_retries"], int) or config["runtime_retries"] < 0
    ):
        raise ValueError("Config key 'runtime_retries' must be a non-negative integer")

    if config.get("start_partition") not in (None, "open", "establish"):
        raise ValueError("Config key 'start_partition' must be one of: open, establish")


def get_parallel_mode(config: dict) -> str:
    """Return 'serial' or 'parallel' from config (default: serial)."""
    mode = config.get("parallel_mode", "serial").lower()
    if mode not in ("serial", "parallel"):
        print(f"Warning: Invalid parallel_mode '{mode}', using 'serial'")
        return "serial"
    return mode


def print_config_summary(config: dict, parallel_mode: str):
    """Print a human-readable summary of the run configuration."""
    images = config["ripple_images"]
    strategies = [normalize_strategy_combo(entry) for entry in config["strategies"]]
    fitnesses = config["fitness_functions"]
    total = len(images) * len(strategies) * len(fitnesses)
    strategy_labels = [format_strategy_combo(combo) for combo in strategies]

    print("\n" + "=" * 70)
    print("CONFIGURATION SUMMARY")
    print("=" * 70)
    print(f"  Config file:          evo/run_evotests.yaml")
    print(f"  Parallel mode:        {parallel_mode.upper()}")
    print(f"  Ripple images ({len(images)}):    {', '.join(images)}")
    print(f"  Mode combos ({len(strategies)}):    {', '.join(strategy_labels)}")
    print(f"  Fitness functions ({len(fitnesses)}): {', '.join(fitnesses)}")
    print(
        f"  Max parallel workers: {config.get('max_parallel_workers', 5)} (per instance)"
    )
    print(f"  Population size:      {config.get('population_size', 10)}")
    print(f"  Mu (parent count):    {config.get('mu', 4)}")
    print(f"  Total num tests:      {config.get('total_num_tests', 500)}")
    print(f"  Individual timeout:   {config.get('individual_timeout_sec', 180)}s")
    print(f"  Runtime retries:     {config.get('runtime_retries', 1)}")
    print(
        f"  Delay bounds:         {config.get('min_delay_ms', 0)}-{config.get('max_delay_ms', 100)} ms"
    )
    print(
        f"  Total runs:           {len(images)} × {len(strategies)} × {len(fitnesses)} = {total}"
    )
    print("=" * 70 + "\n")


def signal_handler(sig, frame):
    print("Received signal", sig, "terminating children...")
    for p in procs:
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except Exception as e:
                print("[SIGTERM] Error killing process", p.pid, ":", e)
    time.sleep(2)
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
    config_file = Path(dirs["cur_dir"]) / "run_evotests.yaml"

    try:
        config = load_config(config_file)
        validate_config(config)
    except (FileNotFoundError, yaml.YAMLError, ValueError) as e:
        print(f"Configuration Error: {e}")
        print(f"Expected config file at: {config_file}")
        sys.exit(1)

    parallel_mode = get_parallel_mode(config)
    print_config_summary(config, parallel_mode)

    if parallel_mode == "parallel":
        print("[run_evotests] PARALLEL mode: all instances will start concurrently.")
    else:
        print("[run_evotests] SERIAL mode: instances will start one after another.")

    # ── read all parameters from config ──────────────────────────────────────
    images = config["ripple_images"]
    strategies = [normalize_strategy_combo(entry) for entry in config["strategies"]]
    fitnesses = config["fitness_functions"]
    population_size = config.get("population_size", 10)
    mu = config.get("mu", 4)
    if mu > population_size:
        print(
            f"Warning: mu={mu} > population_size={population_size}; "
            f"effective mu will be clamped to {population_size} by evotest_parallel.py"
        )
    max_parallel_workers = config.get("max_parallel_workers", 5)
    total_num_tests = config.get("total_num_tests", 500)
    individual_timeout = config.get("individual_timeout_sec", 180)
    runtime_retries = config.get("runtime_retries", 1)
    min_delay_ms = config.get("min_delay_ms")
    max_delay_ms = config.get("max_delay_ms")
    partition_seq = config.get("partition_seq")
    partition_duration = config.get("partition_duration")
    max_partition_duration = config.get("max_partition_duration")
    start_partition = config.get("start_partition")

    log_dir = Path(dirs["logs_dir"]) / get_date_time_strf()
    log_dir.mkdir(parents=True, exist_ok=True)

    idx = 0
    for strategy_combo in strategies:
        strategy_label = format_strategy_combo(strategy_combo)
        for fitness in fitnesses:
            for img in images:
                logs_group_dir = (
                    f"{log_dir}/{img.replace(':','_').replace('/','_')}"
                    f"/{strategy_label}/{fitness}"
                )

                cmd = [
                    sys.executable,
                    "-m",
                    "evo.evotest_parallel",
                    "--logs-group-dir",
                    logs_group_dir,
                    "--ripple-image",
                    img,
                    "--strategy",
                    "ComposedStrategy",
                    "--delay-mode",
                    strategy_combo["delay_mode"],
                    "--partition-mode",
                    strategy_combo["partition_mode"],
                    "--byzz-mode",
                    strategy_combo["byzz_mode"],
                    "--fitness-function",
                    fitness,
                    "--max-parallel-workers",
                    str(max_parallel_workers),
                    "--total-num-tests",
                    str(total_num_tests),
                    "--population-size",
                    str(population_size),
                    "--mu",
                    str(mu),
                    "--individual-timeout-sec",
                    str(individual_timeout),
                    "--runtime-retries",
                    str(runtime_retries),
                ]
                if min_delay_ms is not None:
                    cmd.extend(["--min-delay-ms", str(min_delay_ms)])
                if max_delay_ms is not None:
                    cmd.extend(["--max-delay-ms", str(max_delay_ms)])
                if partition_seq is not None:
                    cmd.extend(["--partition-seq", str(partition_seq)])
                if partition_duration is not None:
                    cmd.extend(["--partition-duration", str(partition_duration)])
                if max_partition_duration is not None:
                    cmd.extend(["--max-partition-duration", str(max_partition_duration)])
                if start_partition is not None:
                    cmd.extend(["--start-partition", str(start_partition)])

                # ensure both the repo root AND the evo/ dir are on PYTHONPATH.
                # evo/evotest_parallel.py uses bare imports (e.g. `from evaluate
                # import ...`) that resolve relative to the evo/ directory.
                env = os.environ.copy()
                root = Path(__file__).resolve().parent.parent   # /rocket
                evo_dir = Path(__file__).resolve().parent        # /rocket/evo
                existing = env.get("PYTHONPATH", "")
                extra = f"{root}:{evo_dir}"
                env["PYTHONPATH"] = extra + (":" + existing if existing else "")

                print(f"\nStarting [{idx}] {img} / {strategy_label} / {fitness}")
                print("  ports: controller + docker host ports are auto-assigned")

                t0 = time.time()
                proc = subprocess.Popen(cmd, env=env, start_new_session=True)
                procs.append(proc)
                idx += 1

                if parallel_mode == "serial":
                    # ⚠️ wait before launching the next instance to avoid Docker
                    # port-binding races (especially on WSL2).
                    proc.wait()
                    print(f"  → completed in {time.time() - t0:.1f}s")

    if parallel_mode == "parallel":
        print(f"\n[run_evotests] Waiting for all {len(procs)} instance(s) to finish...")
        for i, p in enumerate(procs):
            p.wait()
            print(f"  [Instance {i+1}/{len(procs)}] done")


if __name__ == "__main__":
    main()
