"""Tests for CSVLogger."""

import csv
import os
import unittest

import pytest

from rocket_controller.csv_logger import CSVLogger

test_dir = "TEST_LOG_DIR"


class TestCSVLogger(unittest.TestCase):
    """Test CSVLogger class."""

    @classmethod
    def tearDownClass(cls):
        """Remove test directories."""
        os.rmdir("./logs/" + test_dir)
        if len(os.listdir("./logs/")) == 0:
            os.rmdir("./logs/")

    # NOTE: Only run this test from the rocket_controller module, tox does this automatically
    # You are able to run this test regularly, but it will create the logs directory in the wrong location
    def test_construction(self):
        """Test CSVLogger construction."""
        _logger = CSVLogger("TEST", [], test_dir)
        path = "./logs/" + test_dir + "/TEST.csv"
        assert os.path.isfile(path)
        os.remove(path)

    def test_columns(self):
        """Test columns."""
        cols = ["col1", "col2"]
        _logger = CSVLogger("TEST_COLS", cols, test_dir)

        path = "./logs/" + test_dir + "/TEST_COLS.csv"
        with open(path) as file:
            csv_reader = csv.reader(file)
            first_line = next(csv_reader)
            assert first_line == cols

        os.remove(path)

    def test_rows(self):
        """Test writing of rows."""
        cols = ["col1"]
        logger = CSVLogger("TEST_ROWS", cols, test_dir)
        logger.log_row(["1"])
        logger.log_rows([["2"], ["3"]])

        path = "./logs/" + test_dir + "/TEST_ROWS.csv"
        with open(path) as file:
            csv_reader = csv.reader(file)
            next(csv_reader)
            assert next(csv_reader) == ["1"]
            assert next(csv_reader) == ["2"]
            assert next(csv_reader) == ["3"]

        os.remove(path)

    def test_wrong_amount(self):
        """Test failure on wrong column amount."""
        cols = ["col1"]
        logger = CSVLogger("TEST_INVALID", cols, test_dir)

        with pytest.raises(ValueError):
            logger.log_row(["1", "2"])

        path = "./logs/" + test_dir + "/TEST_INVALID.csv"
        os.remove(path)
