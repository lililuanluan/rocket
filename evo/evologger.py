from pathlib import Path
import csv
from evaluate import FITNESS_FUNCTIONS

fieldnames = [
    "generation",
    "individual_id",
    "fitness_type",
    "fitness",
    "total_failures",
] + FITNESS_FUNCTIONS  # add all fitness function names as columns

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
    def init_log(output_dir):
        output_path = Path(output_dir) / "evo_result.csv"
        excluded_output_path = Path(output_dir) / "evo_excluded_runs.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

        with open(excluded_output_path, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=excluded_fieldnames)
            writer.writeheader()

    # TODO: write all evaluation results (fitness) to csv
    @staticmethod
    def write_result_to_csv(result, fitness_function, output_path):

        if output_path is None:
            print("Warning: CSV file path is not set. Skipping writing results to CSV.")
            return

        with open(output_path, "a", newline="") as csvfile:

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

            writer.writerow(to_write)

    @staticmethod
    def write_excluded_run_to_csv(result, fitness_function, output_path):
        if output_path is None:
            print("Warning: excluded CSV file path is not set. Skipping write.")
            return

        with open(output_path, "a", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=excluded_fieldnames)
            writer.writerow(
                {
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
            )
