"""This module contains the SpecChecker class, which is used to perform specification checks on the results of the iterations."""

import csv
import json
from collections import defaultdict
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

    def spec_check(self, iteration: int, nodes: int):
        """
        Do a specification check for the current iteration and log the results.

        Args:
            iteration: The current iteration.
        """
        ledger_file_path = (
            f"logs/{self.log_dir}/iteration-{iteration}/ledger-{iteration}.csv"
        )

        ledgers_data = defaultdict(list)
        try:
            with open(ledger_file_path) as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    # Basic type conversion and validation
                    try:
                        node_id = int(row["peer_id"])
                        ledger_seq = int(row["ledger_seq"])
                        ledger_hash = row["ledger_hash"]
                        parsed_row = {
                            "node_id": node_id,
                            "ledger_seq": ledger_seq,
                            "ledger_hash": ledger_hash,
                        }
                        ledgers_data[ledger_seq].append(parsed_row)
                    except (ValueError, KeyError) as e:
                        logger.error(
                            f"Skipping row due to parsing error: {e} in row: {row}"
                        )
                        continue
        except csv.Error as e:
            logger.critical(f"CSV Error: {e}")
            self.spec_check_logger.log_spec_check(
                iteration, f"CSV Error: {e}", "-", "-"
            )
            return

        if not ledgers_data:
            logger.critical("No valid ledger data found.")
            self.spec_check_logger.log_spec_check(
                iteration, "No valid ledger data found.", "-", "-"
            )
            return

        sorted_keys = sorted(ledgers_data.keys())
        logger.debug(f"Found data for ledger sequences: {sorted_keys}")
        max_seq = sorted_keys[-1]
        min_seq = sorted_keys[0]

        all_hashes_pass = True
        all_sequences_pass = True
        all_ledger_goal_reached = (
            len(ledgers_data[max_seq]) == nodes
        )
        for _, records in ledgers_data.items():
            ledger_hashes_same = all(
               x["ledger_hash"] == records[0]["ledger_hash"] for x in records if x["ledger_hash"] != "NOT FOUND"
            )

            ledger_seq_same = all(
                x["ledger_seq"] == records[0]["ledger_seq"] for x in records if x["ledger_seq"] != -1
            )
            all_hashes_pass &= ledger_hashes_same
            all_sequences_pass &= ledger_seq_same

        self.spec_check_logger.log_spec_check(
            iteration,
            all_ledger_goal_reached,
            all_hashes_pass,
            all_sequences_pass,
        )

        logger.info(
            f"Specification check for iteration {iteration}: "
            f"reached goal ledger: {all_ledger_goal_reached}, "
            f"same ledger hashes: {all_hashes_pass}, same ledger sequences: {all_sequences_pass}"
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
