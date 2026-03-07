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


class EvoLogger:
    @staticmethod
    def init_log(output_dir):
        output_path = Path(output_dir) / "evo_result.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
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
