"""Tests for ActionLogger."""

import csv
import datetime
import os
import unittest

from rocket_controller.csv_logger import ActionLogger, action_log_columns
from rocket_controller.helper import MAX_U32, format_datetime
from tests.default_test_variables import node_0


class TestActionLogger(unittest.TestCase):
    """Test ActionLogger class."""

    @classmethod
    def tearDownClass(cls):
        """Remove test directories."""
        if len(os.listdir("./logs/")) == 0:
            os.rmdir("./logs/")

    def test_action_log(self):
        """Test all functionality of ActionLogger."""
        time = datetime.datetime(2024, 1, 2, 3, 4, 5, 6)
        timestamp_str = format_datetime(time)

        base_dir = "./logs/TEST_ACTION_LOG_DIR"
        directory = f"{base_dir}/{timestamp_str}"
        path_actions = f"{base_dir}/{timestamp_str}/action_log.csv"
        path_nodes = f"{base_dir}/{timestamp_str}/node_info.csv"

        logger = ActionLogger("TEST_ACTION_LOG_DIR/" + timestamp_str, [node_0])
        logger.log_action(0, 1, 0, 1, "propose", "orig data", "new data")
        logger.log_action(3, 1, 0, 1, "validata", "orig data", "new data")
        logger.log_action(MAX_U32, 1, 0, 1, "close", "orig data", "new data")
        logger.close()

        with open(path_actions) as file:
            csv_reader = csv.reader(file)
            assert next(csv_reader) == action_log_columns
            assert next(csv_reader)[1:] == [
                "0",
                "1",
                "0",
                "1",
                "propose",
                "orig data",
                "new data",
            ]
            assert next(csv_reader)[1:] == [
                "3",
                "1",
                "0",
                "1",
                "validata",
                "orig data",
                "new data",
            ]
            assert next(csv_reader)[1:] == [
                MAX_U32.__str__(),
                "1",
                "0",
                "1",
                "close",
                "orig data",
                "new data",
            ]

        with open(path_nodes) as file:
            csv_reader = csv.reader(file)
            assert next(csv_reader) == ["validator_node_info"]
            assert next(csv_reader) == [node_0.__str__()]

        os.remove(path_actions)
        os.remove(path_nodes)
        os.rmdir(directory)
        os.rmdir(base_dir)
