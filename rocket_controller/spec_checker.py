"""This module contains the SpecChecker class, which is used to perform specification checks on the results of the iterations."""

import csv
import json
from typing import Any, List

from loguru import logger

from rocket_controller.csv_logger import SpecCheckLogger


def _get_last_row(file_path: str) -> List[Any]:
    """
    Get the last row from a CSV file.

    Args:
        file_path: The path to the CSV file.

    Returns:
        The last row of the CSV file as a list, or None if the file is empty.
    """
    with open(file_path, newline="") as file:
        reader = csv.reader(file)
        rows = list(reader)
        return rows[-1] if rows else []


class SpecChecker:
    """Class to perform specification checks on the results of the iterations."""

    def __init__(self, log_dir: str):
        """Initialize the SpecChecker object.

        Args:
            log_dir: The directory where the spec check results will be stored.
        """
        self.spec_check_logger: SpecCheckLogger = SpecCheckLogger(log_dir)
        self.log_dir: str = log_dir

    def spec_check(self, iteration: int):
        """
        Do a specification check for the current iteration and log the results.

        Args:
            iteration: The current iteration.
        """
        result_file_path = (
            f"logs/{self.log_dir}/iteration-{iteration}/result-{iteration}.csv"
        )

        try:
            last_row = _get_last_row(result_file_path)
        except Exception as e:
            logger.error(f"Error retrieving last row: {e}")
            self.spec_check_logger.log_spec_check(
                iteration, "error retrieving results", "-", "-"
            )
            return

        try:
            ledger_count = int(last_row[0])
            goal_ledger_count = int(last_row[1])
            ledger_hashes: List = eval(last_row[4])
            ledger_indexes: List = eval(last_row[5])
            ledger_hashes_same = all(x == ledger_hashes[0] for x in ledger_hashes)
            ledger_indexes_same = all(x == ledger_indexes[0] for x in ledger_indexes)

            self.spec_check_logger.log_spec_check(
                iteration,
                ledger_count == goal_ledger_count,
                ledger_hashes_same,
                ledger_indexes_same,
            )

            logger.info(
                f"Specification check for iteration {iteration}: "
                f"reached goal ledger: {ledger_count == goal_ledger_count}, "
                f"same ledger hashes: {ledger_hashes_same}, same ledger indexes: {ledger_indexes_same}"
            )
        except Exception as e:
            logger.error(f"Error during specification check: {e}")
            if last_row[0] == "ledger_count":
                self.spec_check_logger.log_spec_check(
                    iteration, "timeout reached before startup", "-", "-"
                )
            else:
                self.spec_check_logger.log_spec_check(
                    iteration, "error during spec check", "-", "-"
                )

    def aggregate_spec_checks(self):
        """Aggregate the spec check results and write them to a final file."""
        spec_check_file_path = f"logs/{self.log_dir}/spec_check_log.csv"
        agg_spec_check_file_path = f"logs/{self.log_dir}/aggregated_spec_check_log.json"

        try:
            with open(spec_check_file_path, newline="") as file:
                reader = csv.DictReader(file)
                rows = list(reader)

            total_iterations = len(rows)
            correct_runs = sum(
                1
                for row in rows
                if row["reached_goal_ledger"] == "True"
                and row["same_ledger_hashes"] == "True"
                and row["same_ledger_indexes"] == "True"
            )
            timeout_before_startup = sum(
                1
                for row in rows
                if row["reached_goal_ledger"] == "timeout reached before startup"
            )
            errors = sum(1 for row in rows if "error" in row["reached_goal_ledger"])
            failed_termination = sum(
                1 for row in rows if row["reached_goal_ledger"] == "False"
            )
            failed_agreement = sum(
                1
                for row in rows
                if row["same_ledger_hashes"] == "False"
                or row["same_ledger_indexes"] == "False"
            )
            failed_termination_iterations = [
                row["iteration"]
                for row in rows
                if row["reached_goal_ledger"] == "False"
            ]
            failed_agreement_iterations = [
                row["iteration"]
                for row in rows
                if row["same_ledger_hashes"] == "False"
                or row["same_ledger_indexes"] == "False"
            ]

            aggregated_data = {
                "total_iterations": total_iterations,
                "correct_runs": correct_runs,
                "timeout_before_startup": timeout_before_startup,
                "errors": errors,
                "failed_termination": failed_termination,
                "failed_agreement": failed_agreement,
                "failed_termination_iterations": failed_termination_iterations,
                "failed_agreement_iterations": failed_agreement_iterations,
            }

            logger.info(f"Aggregated spec check results: {aggregated_data}")

            with open(agg_spec_check_file_path, mode="w") as file:
                json.dump(aggregated_data, file, indent=4)
        except Exception as e:
            logger.error(f"Error aggregating spec checks: {e}")
