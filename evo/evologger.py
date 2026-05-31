from pathlib import Path
import csv
import time
from evaluate import FITNESS_FUNCTIONS, normalize_objective_seqs


def build_objective_columns(objective_seqs):
    return [f"objective_seq_{seq}" for seq in normalize_objective_seqs(objective_seqs)]


def build_fieldnames(objective_mode="single", objective_seqs=None):
    fields = [
        "generation",
        "individual_id",
        "fitness_type",
        "fitness",
        "total_failures",
    ] + FITNESS_FUNCTIONS

    if str(objective_mode).lower() == "multi":
        fields.extend(
            [
                "objective_metric",
                "objective_status",
                "objective_error",
            ]
        )
        fields.extend(build_objective_columns(objective_seqs))
    return fields

excluded_fieldnames = [
    "generation",
    "individual_id",
    "fitness_type",
    "run_status",
    "runtime_invalid",
    "runtime_invalid_reason",
    "attempts_used",
    "retcode",
    "fitness_assigned",
    "log_dir",
]


class EvoLogger:
    @staticmethod
    def init_log(output_dir, objective_mode="single", objective_seqs=None):
        output_path = Path(output_dir) / "evo_result.csv"
        excluded_output_path = Path(output_dir) / "evo_excluded_runs.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = build_fieldnames(objective_mode, objective_seqs)

        with open(output_path, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

        with open(excluded_output_path, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=excluded_fieldnames)
            writer.writeheader()

    # TODO: write all evaluation results (fitness) to csv
    @staticmethod
    def write_result_to_csv(
        result,
        fitness_function,
        output_path,
        objective_mode="single",
        objective_seqs=None,
    ):

        if output_path is None:
            print("Warning: CSV file path is not set. Skipping writing results to CSV.")
            return

        with open(output_path, "a", newline="") as csvfile:
            fieldnames = build_fieldnames(objective_mode, objective_seqs)
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            eval_result = result.get("eval_result", {})
            fitness_formatted = round(result.get("fitness", 0.0), 3)
            total_failures = eval_result.get("total_failures", 0)

            to_write = {
                "generation": result["generation"],
                "individual_id": result["individual_id"],
                "fitness_type": fitness_function,
                "fitness": fitness_formatted,
                "total_failures": total_failures,
            }
            # 加入所有fitness值
            for func_name in FITNESS_FUNCTIONS:
                fit = eval_result.get(func_name, None)
                if fit is not None:
                    to_write[func_name] = round(fit, 3)
                else:
                    to_write[func_name] = "-"

            if str(objective_mode).lower() == "multi":
                objective_result = result.get("objective_result") or {}
                objective_values = objective_result.get("objectives") or []
                objective_columns = build_objective_columns(objective_seqs)
                to_write["objective_metric"] = fitness_function
                to_write["objective_status"] = "ok" if objective_values else "missing"
                to_write["objective_error"] = "-"
                for idx, column_name in enumerate(objective_columns):
                    value = objective_values[idx] if idx < len(objective_values) else None
                    to_write[column_name] = round(value, 3) if value is not None else "-"

            writer.writerow(to_write)

    @staticmethod
    def write_excluded_run_to_csv(result, fitness_function, output_path):
        if output_path is None:
            print("Warning: excluded CSV file path is not set. Skipping write.")
            return

        row = {
            "generation": result["generation"],
            "individual_id": result["individual_id"],
            "fitness_type": fitness_function,
            "run_status": result.get("run_status", "unknown"),
            "runtime_invalid": result.get("runtime_invalid", False),
            "runtime_invalid_reason": result.get("runtime_invalid_reason"),
            "attempts_used": result.get("attempts_used", 1),
            "retcode": result.get("retcode"),
            "fitness_assigned": result.get("fitness"),
            "log_dir": result.get("log_dir"),
        }

        for attempt in range(3):
            try:
                with open(output_path, "a", newline="") as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=excluded_fieldnames)
                    writer.writerow(row)
                return
            except OSError as exc:
                if attempt < 2:
                    time.sleep(0.2 * (attempt + 1))
                    continue
                print(
                    f"Warning: failed to write excluded run to {output_path}: {exc}. "
                    "Continuing without recording this excluded row."
                )
