import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from evaluate import evaluate_log


def generate_stat_table():
    from pathlib import Path
    import json

    # locate logs root relative to this file
    base_logs = Path(__file__).resolve().parent.parent / "logs"
    if not base_logs.exists():
        raise FileNotFoundError(
            f"logs directory not found at expected location: {base_logs}"
        )

    # pick newest directory under logs by modification time
    candidates = [p for p in base_logs.iterdir() if p.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"no run directories found under {base_logs}")
    latest = max(candidates, key=lambda p: p.stat().st_mtime)

    # for each immediate subdir (e.g., G0T1, G1T1, ...) check aggregated_spec_check_log.json
    correct_res = []
    all_res = []
    failed_aggreement_res = []
    failed_final_res = []
    for sub in sorted(latest.iterdir()):
        if not sub.is_dir():
            continue

        res = evaluate_log(str(sub))
        if res:
            all_res.append(res)
            if res["correct_runs"]:
                correct_res.append(res)
            if res["failed_agreement"]:
                failed_aggreement_res.append(res)
            if res["failed_final_agreement"]:
                failed_final_res.append(res)

    # Prepare output path
    out_dir = Path(__file__).resolve().parent / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_tex = out_dir / "stats.tex"

    res_groups = [all_res, correct_res, failed_aggreement_res, failed_final_res]
    with open(out_tex, "w") as f:
        print(r"\begin{table}[ht]", file=f)
        print(r"\centering", file=f)
        print(r"\begin{tabular}{lcccc}", file=f)
        print(r"\toprule", file=f)
        print(r" & total & correct & failed agreement & failed final \\", file=f)
        print(r"\hline", file=f)

        print(r"\#tests ", file=f, end="")
        for r in res_groups:
            print(f"& {len(r)} ", file=f, end="")
        print(r"\\", file=f)

        print(r"validation time (s)", file=f, end="")
        for r in res_groups:
            # avg +- std
            times = [
                res["mean_validation_time"]
                for res in r
                if res["mean_validation_time"] is not None
            ]
            if times:
                avg = np.mean(times)
                std = np.std(times)
                print(f"& {avg:.2f} $\\pm$ {std:.2f} ", file=f, end="")
            else:
                print(r"& - ", file=f, end="")
        print(r"\\", file=f)

        print(r"\#ProposeSet ", file=f, end="")
        for r in res_groups:
            # avg +- std
            propose_set_counts = [
                res["propose_set_count"]
                for res in r
                if res["propose_set_count"] is not None
            ]
            if propose_set_counts:
                avg = np.mean(propose_set_counts)
                std = np.std(propose_set_counts)
                print(f"& {avg:.2f} $\\pm$ {std:.2f} ", file=f, end="")
            else:
                print(r"& - ", file=f, end="")

        print(r"\\", file=f)
        print(r"\bottomrule", file=f)
        print(r"\end{tabular}", file=f)
        print(r"\end{table}", file=f)

    print(f"Analysis complete. Stats written to {out_tex}")


if __name__ == "__main__":
    generate_stat_table()
