"""Test for SpecCheckLogger."""

import csv
import datetime
import os
import unittest

from xrpl_controller.csv_logger import SpecCheckLogger, spec_check_columns
from xrpl_controller.helper import format_datetime


class TestSpecCheckLogger(unittest.TestCase):
    """Test SpecCheckLogger class."""

    @classmethod
    def tearDownClass(cls):
        """Remove test directories."""
        if len(os.listdir("./logs/")) == 0:
            os.rmdir("./logs/")

    def test_spec_check_log(self):
        """Test all functionality of SpecCheckLogger."""
        time = datetime.datetime(2024, 1, 2, 3, 4, 5, 6)
        timestamp_str = format_datetime(time)

        base_dir = "./logs/TEST_SPEC_CHECK_LOG_DIR"
        directory = f"{base_dir}/{timestamp_str}"
        path_spec_checks = f"{base_dir}/{timestamp_str}/spec_check_log.csv"

        logger = SpecCheckLogger("TEST_SPEC_CHECK_LOG_DIR/" + timestamp_str)
        logger.log_spec_check(1, True, True, True)
        logger.log_spec_check(2, False, True, True)
        logger.log_spec_check(3, "timeout reached before startup", "-", "-")

        with open(path_spec_checks) as file:
            csv_reader = csv.reader(file)
            assert next(csv_reader) == spec_check_columns
            assert next(csv_reader) == ["1", "True", "True", "True"]
            assert next(csv_reader) == ["2", "False", "True", "True"]
            assert next(csv_reader) == ["3", "timeout reached before startup", "-", "-"]

        os.remove(path_spec_checks)
        os.rmdir(directory)
        os.rmdir(base_dir)
