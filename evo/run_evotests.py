import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path


# This script launches a batch of evotest_parallel.py runs with different
# combinations of rippled image, strategy and fitness function.  It ensures
# that the base ports and gRPC ports for each invocation do not overlap by
# assigning them disjoint ranges based on a simple index.  Logs are placed in
# a hierarchy that includes the image/strategy/fitness to make later analysis
# easier.


def main():
    images = ["xrpllabsofficial/xrpld:2.6.0"]
    strategies = ["EvoDelayStrategy", "RandomDelayByzzStrategy"]
    # choose real fitness names from the allowed list; "fitness_function" was
    # a placeholder and not a valid choice for the CLI parser
    fitnesses = ["mean_validation_time", "num_getledger_messages"]

    # compute a unique timestamp for this batch so all processes share a
    # common parent log directory
    batch_id = datetime.now().strftime("%Y_%m_%d_%Hh%Mm_%Ss")

    procs = []
    idx = 0
    for img in images:
        for strategy in strategies:
            for fitness in fitnesses:
                # allocate non‑overlapping port ranges.  we give each process a
                # block of 1000 for the ripple ports and a block of 10 for gRPC.
                base_peer = 60000 + idx * 1000
                base_ws = 61000 + idx * 1000
                base_ws_admin = 62000 + idx * 1000
                base_rpc = 63000 + idx * 1000
                grpc_base = 50051 + idx * 10

                log_dir = f"{batch_id}/{img.replace(':','_')}/{strategy}/{fitness}"

                cmd = [
                    sys.executable,
                    "-m",
                    "evo.evotest_parallel",
                    "--ripple-image",
                    img,
                    "--strategy",
                    strategy,
                    "--fitness-function",
                    fitness,
                    "--run-id",
                    batch_id,
                    "--grpc-base-port",
                    str(grpc_base),
                    "--base-port-peer",
                    str(base_peer),
                    "--base-port-ws",
                    str(base_ws),
                    "--base-port-ws-admin",
                    str(base_ws_admin),
                    "--base-port-rpc",
                    str(base_rpc),
                    "--max-parallel-workers",
                    str(5),
                    # logs dir and test-log-dir are computed inside the
                    # called script based on run-id; no need to pass them
                    # explicitly
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
                proc = subprocess.Popen(cmd, env=env)
                procs.append(proc)
                idx += 1

    # wait for all children to exit
    for p in procs:
        p.wait()


if __name__ == "__main__":
    import sys
    from pathlib import Path

    main()
