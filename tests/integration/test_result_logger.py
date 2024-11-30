"""Tests for ResultLogger."""

import csv
import datetime
import os
import unittest

from xrpl_controller.csv_logger import (
    ResultLogger,
    result_log_columns,
)
from xrpl_controller.helper import format_datetime


class TestResultLogger(unittest.TestCase):
    """Test ResultLogger class."""

    @classmethod
    def tearDownClass(cls):
        """Remove test directories."""
        if len(os.listdir("./logs/")) == 0:
            os.rmdir("./logs/")

    def test_action_log(self):
        """Test all functionality of ActionLogger."""
        time = datetime.datetime(2024, 1, 2, 3, 4, 5, 6)
        timestamp_str = format_datetime(time)

        base_dir = "./logs/TEST_RESULT_LOG_DIR"
        directory = f"{base_dir}/{timestamp_str}"
        path_results = f"{base_dir}/{timestamp_str}/result_log.csv"

        logger = ResultLogger("TEST_RESULT_LOG_DIR/" + timestamp_str)
        logger.log_result(1, 5, 3.00, [1234, 1234], ["hash123", "hash123"], [1, 1])
        logger.log_result(2, 5, 3.00, [2234, 2234], ["hash123", "hash123"], [2, 2])
        logger.log_result(3, 5, 3.00, [3234, 3234], ["hash123", "hash123"], [3, 3])
        logger.close()

        with open(path_results) as file:
            csv_reader = csv.reader(file)
            assert next(csv_reader) == result_log_columns
            assert next(csv_reader) == [
                "1",
                "5",
                "3.000000",
                "[1234, 1234]",
                "['hash123', 'hash123']",
                "[1, 1]",
            ]
            assert next(csv_reader) == [
                "2",
                "5",
                "3.000000",
                "[2234, 2234]",
                "['hash123', 'hash123']",
                "[2, 2]",
            ]
            assert next(csv_reader) == [
                "3",
                "5",
                "3.000000",
                "[3234, 3234]",
                "['hash123', 'hash123']",
                "[3, 3]",
            ]

        os.remove(path_results)
        os.rmdir(directory)
        os.rmdir(base_dir)
