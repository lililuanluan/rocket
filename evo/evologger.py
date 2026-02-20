from pathlib import Path
import csv


class EvoLogger:
    @staticmethod
    def init_log(output_dir):
        output_path = Path(output_dir) / "evo_result.csv"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", newline="") as csvfile:
            fieldnames = [
                "generation",
                "individual_id",
                "fitness_type",
                "fitness",
                "mean_validation_time",
                "num_propose_set",
                "total_failures",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()

    # TODO: write all evaluation results (fitness) to csv
    @staticmethod
    def write_result_to_csv(result, fitness_function, output_path):

        if output_path is None:
            print("Warning: CSV file path is not set. Skipping writing results to CSV.")
            return

        with open(output_path, "a", newline="") as csvfile:
            fieldnames = [
                "generation",
                "individual_id",
                "fitness_type",
                "fitness",
                "mean_validation_time",
                "num_propose_set",
                "total_failures",
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            eval_result = result["eval_result"]
            fitness_formatted = round(result["fitness"], 3)
            mean_time_formatted = (
                round(eval_result["mean_validation_time"], 3)
                if eval_result["mean_validation_time"]
                else 0.0
            )

            writer.writerow(
                {
                    "generation": result["generation"],
                    "individual_id": result["individual_id"],
                    "fitness_type": fitness_function,
                    "fitness": fitness_formatted,
                    "mean_validation_time": mean_time_formatted,
                    "num_propose_set": eval_result["num_propose_set"],
                    "total_failures": eval_result["total_failures"],
                }
            )
