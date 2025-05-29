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

    def validation_check(self, iteration: int, ) -> None:
        ledger_file_path = (
            f"logs/{self.log_dir}/iteration-{iteration}/tx_proposals-{iteration}.csv"
        )


    def spec_check(self, iteration: int, nodes: int, goal_ledger_seq: int, byzantine_nodes: List[int] = []) -> None:
        """
        Do a specification check for the current iteration and log the results.

        Args:
            goal_ledger_seq: The goal ledger sequence number.
            nodes: Amount of nodes in the network.
            iteration: The current iteration.
        """
        tx_proposals_file_path = (
            f"logs/{self.log_dir}/iteration-{iteration}/tx_proposals-{iteration}.csv"
        )

        tx_honest_proposals_data = defaultdict(list)
        try:
            with open(tx_proposals_file_path) as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    try:
                        ledger_seq = int(row["next_ledger_seq"]) # this transaction can be included in the next ledger sequence (so its this sequence or the following sequences), tmtransaction packet is logged in between closing the ledger with sequence i and opening ledger with sequence i+1, so this tmtransaction cannot be included in current ledger, only in the next ledger
                        tx_hash = row["tx_hash"]
                        sender_id = int(row["sender_peer_id"])
                        if sender_id in byzantine_nodes:
                            continue
                        tx_honest_proposals_data[ledger_seq].append(tx_hash)
                    except (ValueError, KeyError) as e:
                        logger.error(
                            f"Skipping row due to parsing error: {e} in row: {row}"
                        )
                        continue
        except csv.Error as e:
            logger.critical(f"CSV Error: {e}")
            return

        if not tx_honest_proposals_data:
            logger.critical("No valid tx_proposals data found.")
            return

        
        ledger_file_path = (
            f"logs/{self.log_dir}/iteration-{iteration}/ledger-{iteration}.csv"
        )

        ledgers_data = defaultdict(list)
        try:
            with open(ledger_file_path) as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    # Basic type conversion and validation
                    if "validated" in row["ledger_seq"] :
                        continue
                    try:
                        node_id = int(row["peer_id"])
                        ledger_seq = int(row["ledger_seq"])
                        ledger_hash = row["ledger_hash"]
                        transactions = eval(row["transactions"]) if row["transactions"] else []
                        parsed_row = {
                            "node_id": node_id,
                            "ledger_seq": ledger_seq,
                            "ledger_hash": ledger_hash,
                            "transactions": transactions,
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
                iteration, f"CSV Error: {e}", "-", "-", "-", "-"
            )
            return

        if not ledgers_data:
            logger.critical("No valid ledger data found.")
            self.spec_check_logger.log_spec_check(
                iteration, "No valid ledger data found.", "-", "-", "-", "-"
            )
            return

        sorted_keys = sorted(ledgers_data.keys())
        logger.debug(f"Found data for ledger sequences: {sorted_keys}")
        max_seq = sorted_keys[-1]
        min_seq = sorted_keys[0]

        all_hashes_pass = True
        all_sequences_pass = True
        all_transactions_validated = True
        honest_nodes = [node for node in range(nodes) if node not in byzantine_nodes]

        all_ledger_goal_reached = (
            len([record for record in ledgers_data[max_seq] if record['node_id'] in honest_nodes]) == len(honest_nodes)
            and max_seq >= goal_ledger_seq
        )
        for _, records in ledgers_data.items():
            honest_records = [record for record in records if record['node_id'] in honest_nodes]

            validated_records = [x for x in honest_records if x.get("validated") == "True"]

            ledger_hashes_same = all(
                x["ledger_hash"] == validated_records[0]["ledger_hash"] for x in validated_records if x["ledger_hash"] != "NOT FOUND"
            )

            ledger_seq_same = all(
                x["ledger_seq"] == honest_records[0]["ledger_seq"] for x in honest_records if x["ledger_seq"] != -1
            )

            # for each transaction for this ledger sequence check if it is in the tx_proposals_data for sequences from 1 until this sequence ledger_seq-1

            all_hashes_pass &= ledger_hashes_same
            all_sequences_pass &= ledger_seq_same

            for record in honest_records:
                ledger_seq = record["ledger_seq"]
                transactions = record["transactions"]
                # Check if each transaction is in the tx_proposals_data for sequences from 1 to ledger_seq - 1
                for tx in transactions:
                    found_in_proposals = any(
                        tx in tx_honest_proposals_data[seq]
                        for seq in range(1, ledger_seq) # 1 to ledger_seq - 1
                    )
                    if not found_in_proposals:
                        logger.error(
                            f"Transaction {tx} in ledger sequence {ledger_seq} not found in tx_proposals_data for earlier sequences."
                        )
                        all_transactions_validated = False
                        break

        # Check if sequence numbers increase by 1 for each node ID in honest nodes
        all_sequence_increments_pass = True
        for node_id in honest_nodes:
            node_sequences = sorted(
                [ledger_seq for ledger_seq, records in ledgers_data.items() if any(record['node_id'] == node_id for record in records)]
            )
            if not all(node_sequences[i] + 1 == node_sequences[i + 1] for i in range(len(node_sequences) - 1)):
                all_sequence_increments_pass = False
                break

        self.spec_check_logger.log_spec_check(
            iteration,
            all_ledger_goal_reached,
            all_hashes_pass,
            all_sequences_pass,
            all_sequence_increments_pass,
            all_transactions_validated,
        )

        logger.info(
            f"Specification check for iteration {iteration}: "
            f"reached goal ledger: {all_ledger_goal_reached}, "
            f"same ledger hashes: {all_hashes_pass}, same ledger sequences: {all_sequences_pass}, "
            f"sequence increments: {all_sequence_increments_pass}, "
            f"transactions validated: {all_transactions_validated}"
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
                and row["sequence_increments"] == "True"
                and row["transactions_validated"] == "True"
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
            failed_integrity = sum(
                1 for row in rows
                if row["sequence_increments"] == "False"
            )
            failed_validity = sum(
                1 for row in rows
                if row["transactions_validated"] == "False"
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
            failed_integrity_iterations = [
                row["iteration"]
                for row in rows
                if row["sequence_increments"] == "False"
            ]
            failed_validity_iterations = [
                row["iteration"]
                for row in rows
                if row["transactions_validated"] == "False"
            ]

            aggregated_data = {
                "total_iterations": total_iterations,
                "correct_runs": correct_runs,
                "timeout_before_startup": timeout_before_startup,
                "errors": errors,
                "failed_termination": failed_termination,
                "failed_agreement": failed_agreement,
                "failed_integrity": failed_integrity,
                "failed_validity": failed_validity,
                "failed_termination_iterations": failed_termination_iterations,
                "failed_agreement_iterations": failed_agreement_iterations,
                "failed_integrity_iterations": failed_integrity_iterations,
                "failed_validity_iterations": failed_validity_iterations,
            }

            logger.info(f"Aggregated spec check results: {aggregated_data}")

            with open(agg_spec_check_file_path, mode="w") as file:
                json.dump(aggregated_data, file, indent=4)
        except Exception as e:
            logger.error(f"Error aggregating spec checks: {e}")
