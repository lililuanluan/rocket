"""Tests for the SpecChecker class."""

import csv
import json
import os
import unittest
from unittest.mock import patch

from xrpl_controller.spec_checker import SpecChecker


class TestSpecChecker(unittest.TestCase):
    """Test aggregate_spec_checks method."""

    @classmethod
    def tearDownClass(cls):
        """Remove test directories and files."""
        if os.path.exists("./logs/TEST_SPECCHECK_DIR"):
            for file in os.listdir("./logs/TEST_SPECCHECK_DIR"):
                os.remove(f"./logs/TEST_SPECCHECK_DIR/{file}")
            os.rmdir("./logs/TEST_SPECCHECK_DIR")

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
