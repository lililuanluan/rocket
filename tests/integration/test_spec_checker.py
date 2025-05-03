"""Tests for the SpecChecker class."""

import csv
import json
import os
import unittest

from rocket_controller.spec_checker import SpecChecker


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

    def test_agg_spec_checks_no_spec_check_file(self):
        """Test the aggregate_spec_checks method when there is no spec_check_log.csv file."""
        spec_checker = SpecChecker("TEST_SPECCHECK_DIR")
        os.remove("./logs/TEST_SPECCHECK_DIR/spec_check_log.csv")
        spec_checker.aggregate_spec_checks()

        self.assertFalse(
            os.path.exists("./logs/TEST_SPECCHECK_DIR/aggregated_spec_check_log.json")
        )
