"""Tests for the SpecChecker class."""

import csv
import json
import os
import unittest
from unittest.mock import patch

from xrpl_controller.spec_checker import SpecChecker, _get_last_row


class TestSpecChecker(unittest.TestCase):
    """Test aggregate_spec_checks method."""

    @classmethod
    def setUpClass(cls):
        """Create test directories and files."""
        os.makedirs("./logs/TEST_SPECCHECK_DIR")

    @classmethod
    def tearDownClass(cls):
        """Remove test directories and files."""
        if os.path.exists("./logs/TEST_SPECCHECK_DIR"):
            for file in os.listdir("./logs/TEST_SPECCHECK_DIR"):
                os.remove(f"./logs/TEST_SPECCHECK_DIR/{file}")
            os.rmdir("./logs/TEST_SPECCHECK_DIR")
        if len(os.listdir("./logs/")) == 0:
            os.rmdir("./logs/")

    @patch("xrpl_controller.spec_checker._get_last_row")
    def test_spec_check(self, mock_get_last_row):
        """Test the spec_check method."""
        mock_get_last_row.return_value = [
            "10",
            "10",
            "",
            "",
            "['hash1', 'hash1']",
            "['index1', 'index1']",
        ]
        spec_checker = SpecChecker("TEST_SPECCHECK_DIR")
        spec_checker.spec_check(1)

        mock_get_last_row.assert_called_once_with(
            "logs/TEST_SPECCHECK_DIR/iteration-1/result-1.csv"
        )

        with open("./logs/TEST_SPECCHECK_DIR/spec_check_log.csv", newline="") as file:
            reader = csv.DictReader(file)
            rows = list(reader)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[-1]["iteration"], "1")
            self.assertEqual(rows[-1]["reached_goal_ledger"], "True")
            self.assertEqual(rows[-1]["same_ledger_hashes"], "True")
            self.assertEqual(rows[-1]["same_ledger_indexes"], "True")

    def test_aggregate_spec_checks(self):
        """Test the aggregate_spec_checks method."""
        spec_checker = SpecChecker("TEST_SPECCHECK_DIR")
        filepath = "./logs/TEST_SPECCHECK_DIR/spec_check_log.csv"
        with open(filepath, mode="a", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["1", "True", "True", "True"])
            writer.writerow(["2", "False", "True", "True"])
            writer.writerow(["3", "timeout reached before startup", "-", "-"])
            writer.writerow(["4", "error retrieving results", "-", "-"])
        spec_checker.aggregate_spec_checks()

        with open("./logs/TEST_SPECCHECK_DIR/aggregated_spec_check_log.json") as file:
            aggregated_data = json.load(file)
            self.assertEqual(aggregated_data["total_iterations"], 4)
            self.assertEqual(aggregated_data["correct_runs"], 1)
            self.assertEqual(aggregated_data["timeout_before_startup"], 1)
            self.assertEqual(aggregated_data["errors"], 1)
            self.assertEqual(aggregated_data["failed_termination"], 1)
            self.assertEqual(aggregated_data["failed_agreement"], 0)
            self.assertEqual(aggregated_data["failed_termination_iterations"], ["2"])
            self.assertEqual(aggregated_data["failed_agreement_iterations"], [])

    def test_get_last_row(self):
        """Test the _get_last_row method."""
        filepath = "./logs/TEST_SPECCHECK_DIR/result-1.csv"
        with open(filepath, mode="w", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(
                [
                    "ledger_count",
                    "goal_ledger_count",
                    "time_to_consensus",
                    "close_times",
                    "ledger_hashes",
                    "ledger_indexes",
                ]
            )
            writer.writerow(
                ["10", "10", "", "", "['hash1', 'hash1']", "['index1', 'index1']"]
            )
        last_row = _get_last_row(filepath)
        self.assertEqual(
            last_row, ["10", "10", "", "", "['hash1', 'hash1']", "['index1', 'index1']"]
        )

    @patch("xrpl_controller.spec_checker._get_last_row")
    def test_spec_check_error_retrieving_last_row(self, mock_get_last_row):
        """Test the spec_check method when there is an error retrieving the last row."""
        mock_get_last_row.side_effect = Exception("Error")
        spec_checker = SpecChecker("TEST_SPECCHECK_DIR")
        spec_checker.spec_check(1)

        with open("./logs/TEST_SPECCHECK_DIR/spec_check_log.csv", newline="") as file:
            reader = csv.DictReader(file)
            rows = list(reader)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[-1]["iteration"], "1")
            self.assertEqual(
                rows[-1]["reached_goal_ledger"], "error retrieving results"
            )
            self.assertEqual(rows[-1]["same_ledger_hashes"], "-")
            self.assertEqual(rows[-1]["same_ledger_indexes"], "-")

    @patch("xrpl_controller.spec_checker._get_last_row")
    def test_spec_check_error_during_spec_check_1(self, mock_get_last_row):
        """Test the spec_check method when there is an error, if the last row is the header row."""
        mock_get_last_row.return_value = [
            "ledger_count",
            "goal_ledger_count",
            "time_to_consensus",
            "close_times",
            "ledger_hashes",
            "ledger_indexes",
        ]
        spec_checker = SpecChecker("TEST_SPECCHECK_DIR")
        spec_checker.spec_check(1)

        with open("./logs/TEST_SPECCHECK_DIR/spec_check_log.csv", newline="") as file:
            reader = csv.DictReader(file)
            rows = list(reader)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[-1]["iteration"], "1")
            self.assertEqual(
                rows[-1]["reached_goal_ledger"], "timeout reached before startup"
            )
            self.assertEqual(rows[-1]["same_ledger_hashes"], "-")
            self.assertEqual(rows[-1]["same_ledger_indexes"], "-")

    @patch("xrpl_controller.spec_checker._get_last_row")
    def test_spec_check_error_during_spec_check_2(self, mock_get_last_row):
        """Test the spec_check method when there is an error, if the last row is not the header row."""
        mock_get_last_row.return_value = [
            "error",
            "goal_ledger_count",
            "time_to_consensus",
            "close_times",
            "ledger_hashes",
            "ledger_indexes",
        ]
        spec_checker = SpecChecker("TEST_SPECCHECK_DIR")
        spec_checker.spec_check(1)

        with open("./logs/TEST_SPECCHECK_DIR/spec_check_log.csv", newline="") as file:
            reader = csv.DictReader(file)
            rows = list(reader)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[-1]["iteration"], "1")
            self.assertEqual(rows[-1]["reached_goal_ledger"], "error during spec check")
            self.assertEqual(rows[-1]["same_ledger_hashes"], "-")
            self.assertEqual(rows[-1]["same_ledger_indexes"], "-")

    def test_agg_spec_checks_no_spec_check_file(self):
        """Test the aggregate_spec_checks method when there is no spec_check_log.csv file."""
        spec_checker = SpecChecker("TEST_SPECCHECK_DIR")
        os.remove("./logs/TEST_SPECCHECK_DIR/spec_check_log.csv")
        spec_checker.aggregate_spec_checks()

        self.assertFalse(
            os.path.exists("./logs/TEST_SPECCHECK_DIR/aggregated_spec_check_log.json")
        )
