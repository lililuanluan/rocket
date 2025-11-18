import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from evaluate import evaluate_log

from pathlib import Path
import json


def generate_node_seq_validation_time_table(result, outfile, caption=None):
    df = result if isinstance(result, pd.DataFrame) else pd.read_csv(result)
    print(f"Generating node-seq-validation-time table to {outfile} from {result}")

    with open(outfile, "w") as f:
        # 行：ledger_seq
        # 列：node_id
        # 先创建一个字典，node_id, ledger_seq -> time_to_validation，画表格时如果对应的数据不存在就画 ‘-’
        data_dict = {}
        for _, row in df.iterrows():
            node_id = row["node_id"]
            ledger_seq = row["ledger_seq"]
            time_to_validation = row["time_to_validation"]
            data_dict[(node_id, ledger_seq)] = time_to_validation
        node_ids = sorted(df["node_id"].unique())
        ledger_seqs = sorted(df["ledger_seq"].unique())
        with open(outfile, "w") as f:
            # 写表头
            print(r"\begin{table}[ht]", file=f)
            print(r"\centering", file=f)
            
            print(r"\begin{tabular}{" + "l" + "c" * len(node_ids) + "}", file=f)
            print(r"\toprule", file=f)
            print("Ledger Seq", end="", file=f)
            for node_id in node_ids:
                print(f" & Node {node_id}", end="", file=f)
            print(r" \\", file=f)
            print(r"\hline", file=f)

            # 写每一行
            for ledger_seq in ledger_seqs:
                print(f"{ledger_seq}", end="", file=f)
                for node_id in node_ids:
                    time_to_validation = data_dict.get((node_id, ledger_seq), None)
                    if time_to_validation is not None:
                        print(f" & {time_to_validation:.3f}", end="", file=f)
                    else:
                        print(" & -", end="", file=f)
                print(r" \\", file=f)
            print(r"\bottomrule", file=f)
            print(r"\end{tabular}", file=f)
            if caption:
                print(r"\caption{" + caption + "}", file=f)
            print(r"\end{table}", file=f)
        print(f"Table written to {outfile}")


def generate_stat_table():

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
    with open(
        Path(__file__).resolve().parent / "out" / "val_time_tables.tex", "w"
    ) as f:
        for i, sub in enumerate(sorted(latest.iterdir())):
            if not sub.is_dir():
                continue

            def str_res(res):
                return json.dumps(res["agg_spec_check"]).replace("_", r"\_")
            # sub=/Users/lli21/rocket/logs/2025_11_18_20h16m/G0T1 -> G0T1
            res = evaluate_log(str(sub))
            table_outfile = (
                Path(__file__).resolve().parent
                / "out"
                / f"{sub.name}_validation_time.tex"
            )
            generate_node_seq_validation_time_table(
                sub / "iteration-1" / "result-1.csv",
                table_outfile,
                caption=f"test {i+1}, res: {str_res(res) if res else ''} ",
            )
            f.write(r"\input{out/" + table_outfile.name + "}\n")

            
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


def build_latex():
    # 自动编译 main.tex 生成 PDF
    import subprocess

    main_tex = Path(__file__).resolve().parent / "main.tex"
    build_dir = Path(__file__).resolve().parent.parent / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    pdf_out = build_dir / "main.pdf"
    try:
        subprocess.run(
            [
                "pdflatex",
                "-interaction=nonstopmode",
                f"-output-directory={build_dir}",
                str(main_tex),
            ],
            check=True,
        )
        print(f"PDF generated at {pdf_out}")
    except Exception as e:
        print(f"pdflatex failed: {e}")


if __name__ == "__main__":
    generate_stat_table()
    build_latex()
