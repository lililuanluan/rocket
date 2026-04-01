import subprocess
import sys
import time
from pathlib import Path
import yaml
from utils import get_dirs, get_date_time_strf
import os
import signal


procs = []


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

    for key in ["max_parallel_workers", "individual_timeout_sec", "population_size", "total_num_tests"]:
        if key in config and (not isinstance(config[key], int) or config[key] <= 0):
            raise ValueError(f"Config key '{key}' must be a positive integer")

    if "mu" in config and (not isinstance(config["mu"], int) or config["mu"] <= 0):
        raise ValueError("Config key 'mu' must be a positive integer")


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
    strategies = config["strategies"]
    fitnesses = config["fitness_functions"]
    total = len(images) * len(strategies) * len(fitnesses)

    print("\n" + "=" * 70)
    print("CONFIGURATION SUMMARY")
    print("=" * 70)
    print(f"  Config file:          evo/run_evotests.yaml")
    print(f"  Parallel mode:        {parallel_mode.upper()}")
    print(f"  Ripple images ({len(images)}):    {', '.join(images)}")
    print(f"  Strategies ({len(strategies)}):      {', '.join(strategies)}")
    print(f"  Fitness functions ({len(fitnesses)}): {', '.join(fitnesses)}")
    print(
        f"  Max parallel workers: {config.get('max_parallel_workers', 5)} (per instance)"
    )
    print(f"  Population size:      {config.get('population_size', 10)}")
    print(f"  Mu (parent count):    {config.get('mu', 4)}")
    print(f"  Total num tests:      {config.get('total_num_tests', 500)}")
    print(f"  Individual timeout:   {config.get('individual_timeout_sec', 180)}s")
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
    strategies = config["strategies"]
    fitnesses = config["fitness_functions"]
    port_start = config.get("port_start", 60000)
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

    log_dir = Path(dirs["logs_dir"]) / get_date_time_strf()
    log_dir.mkdir(parents=True, exist_ok=True)

    # read number_of_nodes from network.yaml to compute per-population port range
    network_yaml = Path(dirs["cur_dir"]) / "network.yaml"
    max_num_nodes = 10
    try:
        with open(network_yaml, "r") as f:
            max_num_nodes = int(yaml.safe_load(f).get("number_of_nodes", max_num_nodes))
    except Exception:
        print(
            f"Warning: could not read {network_yaml}, using max_num_nodes={max_num_nodes}"
        )

    # each test occupies (1 + num_nodes*4) ports; a whole population needs that × population_size
    population_port_range = (1 + max_num_nodes * 4) * population_size

    idx = 0
    for strategy in strategies:
        for fitness in fitnesses:
            for img in images:
                logs_group_dir = (
                    f"{log_dir}/{img.replace(':','_').replace('/','_')}"
                    f"/{strategy}/{fitness}"
                )
                base_port_population = port_start + idx * population_port_range

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
                    str(max_parallel_workers),
                    "--total-num-tests",
                    str(total_num_tests),
                    "--population-size",
                    str(population_size),
                    "--mu",
                    str(mu),
                    "--individual-timeout-sec",
                    str(individual_timeout),
                ]

                # ensure both the repo root AND the evo/ dir are on PYTHONPATH.
                # evo/evotest_parallel.py uses bare imports (e.g. `from evaluate
                # import ...`) that resolve relative to the evo/ directory.
                env = os.environ.copy()
                root = Path(__file__).resolve().parent.parent   # /rocket
                evo_dir = Path(__file__).resolve().parent        # /rocket/evo
                existing = env.get("PYTHONPATH", "")
                extra = f"{root}:{evo_dir}"
                env["PYTHONPATH"] = extra + (":" + existing if existing else "")

                print(f"\nStarting [{idx}] {img} / {strategy} / {fitness}")
                print(
                    "  ports:",
                    base_port_population,
                    "–",
                    base_port_population + population_port_range - 1,
                )

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
