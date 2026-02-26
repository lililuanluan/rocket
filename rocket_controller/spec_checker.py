"""This module contains the SpecChecker class, which is used to perform specification checks on the results of the iterations."""

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, List, Iterable, Optional, Set

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

    def __init__(self, log_dir: Path):
        """Initialize the SpecChecker object.

        Args:
            log_dir: The directory where the spec check results will be stored.
        """
        self.spec_check_logger: SpecCheckLogger = SpecCheckLogger(log_dir)
        self.log_dir: Path = log_dir

    def spec_check(self, iteration: int, exclude_node_ids: Optional[Iterable[int]] = None):
        """
        Do a specification check for the current iteration and log the results.

        Args:
            iteration: The current iteration.
        """
        result_file_path = self.log_dir / f"iteration-{iteration}" / f"result-{iteration}.csv"

        byzantine_nodes: Set[int] = set(exclude_node_ids) if exclude_node_ids is not None else set()
        honest_nodes: Set[int] = set()
        logger.info(f"spec checking iteration {iteration}, excluding nodes: {byzantine_nodes}")

        ledgers_data = defaultdict(list)
        try:
            with open(result_file_path) as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    # Basic type conversion and validation
                    try:
                        node_id = int(row["node_id"])
                        # Skip byzantine/excluded nodes
                        if node_id in byzantine_nodes:
                            continue
                        honest_nodes.add(node_id)
                        ledger_seq = int(row["ledger_seq"])
                        goal_ledger_seq = int(row["goal_ledger_seq"])
                        ledger_hash = row["ledger_hash"]
                        ledger_index = int(row["ledger_index"])
                        parsed_row = {
                            "node_id": node_id,
                            "ledger_seq": ledger_seq,
                            "goal_ledger_seq": goal_ledger_seq,
                            "ledger_hash": ledger_hash,
                            "ledger_index": ledger_index,
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
        all_indexes_pass = True
        # goal_ledger_pass: only True if all honest nodes reached goal AND
        # all ledger_hash values at goal_ledger_seq are identical.
        goal_ledger_pass = (max_seq >= goal_ledger_seq and len([r for r in ledgers_data.get(goal_ledger_seq, []) if r['node_id'] in honest_nodes]) == len(honest_nodes) and all(x['ledger_hash'] == ledgers_data[goal_ledger_seq][0]['ledger_hash'] for x in ledgers_data.get(goal_ledger_seq, [])))
        all_ledger_goal_reached = (
            max_seq >= goal_ledger_seq and
            len([record for record in ledgers_data[goal_ledger_seq] if record['node_id'] in honest_nodes]) == len(honest_nodes)
        )
        for _, records in ledgers_data.items():
            ledger_hashes_same = all(
                x["ledger_hash"] == records[0]["ledger_hash"] for x in records
            )
            ledger_indexes_same = all(
                x["ledger_index"] == records[0]["ledger_index"] for x in records
            )
            all_hashes_pass &= ledger_hashes_same
            all_indexes_pass &= ledger_indexes_same

        self.spec_check_logger.log_spec_check(
            iteration,
            all_ledger_goal_reached,
            all_hashes_pass,
            all_indexes_pass,
            goal_ledger_pass,
        )

        logger.info(
            f"Specification check for iteration {iteration}: "
            f"reached goal ledger: {all_ledger_goal_reached}, "
            f"same ledger hashes: {all_hashes_pass}, same ledger indexes: {all_indexes_pass}, same goal ledger hash: {goal_ledger_pass}"
        )

    def aggregate_spec_checks(self):
        """Aggregate the spec check results and write them to a final file."""
        spec_check_file_path = self.log_dir / "spec_check_log.csv"
        agg_spec_check_file_path = self.log_dir / "aggregated_spec_check_log.json"

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
            failed_final_agreement = sum(
                1
                for row in rows
                if row["same_goal_ledger_hash"] == "False" and row["reached_goal_ledger"] == "True"
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
                "failed_final_agreement": failed_final_agreement,
            }

            logger.info(f"Aggregated spec check results: {aggregated_data}")

            with open(Path(__file__).parent / "../evo/out/error.log", "a") as error_log:
                if aggregated_data["correct_runs"] != total_iterations:
                    error_log.write(f"FAILED RUN, final agreement failed: {failed_final_agreement}\n")
                else:
                    error_log.write(f"CORRECT RUN\n")

            with open(agg_spec_check_file_path, mode="w") as file:
                json.dump(aggregated_data, file, indent=4)
        except Exception as e:
            logger.error(f"Error aggregating spec checks: {e}")
