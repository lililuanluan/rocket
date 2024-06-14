"""Tests for ActionLogger."""

import csv
import datetime
import os

from xrpl_controller.core import MAX_U32, format_datetime
from xrpl_controller.csv_logger import ActionLogger, action_log_columns
from xrpl_controller.validator_node_info import (
    SocketAddress,
    ValidatorKeyData,
    ValidatorNode,
)

node = ValidatorNode(
    SocketAddress("test_peer", 10),
    SocketAddress("test-ws-pub", 20),
    SocketAddress("test-ws-adm", 30),
    SocketAddress("test-rpc", 40),
    ValidatorKeyData("status", "key", "K3Y", "PUB", "T3ST"),
)


def test_action_log():
    """Test all functionality of ActionLogger."""
    time = datetime.datetime(2024, 1, 2, 3, 4, 5, 6)
    timestamp_str = format_datetime(time)

    base_dir = "./logs/action_logs/TEST_ACTION_LOG_DIR"
    directory = f"{base_dir}/{timestamp_str}"
    path_actions = f"{base_dir}/{timestamp_str}/action_log.csv"
    path_nodes = f"{base_dir}/{timestamp_str}/node_info.csv"

    logger = ActionLogger("TEST_ACTION_LOG_DIR/" + timestamp_str, [node])
    logger.log_action(0, 0, 1, "propose", "orig data", "new date")
    logger.log_action(3, 0, 1, "validate", "orig data", "new date")
    logger.log_action(MAX_U32, 0, 1, "close", "orig data", "new date")
    logger.close()

    with open(path_actions) as file:
        csv_reader = csv.reader(file)
        assert next(csv_reader) == action_log_columns
        assert next(csv_reader)[1:] == [
            "0",
            "0",
            "1",
            "propose",
            "orig data",
            "new date",
        ]
        assert next(csv_reader)[1:] == [
            "3",
            "0",
            "1",
            "validate",
            "orig data",
            "new date",
        ]
        assert next(csv_reader)[1:] == [
            MAX_U32.__str__(),
            "0",
            "1",
            "close",
            "orig data",
            "new date",
        ]

    with open(path_nodes) as file:
        csv_reader = csv.reader(file)
        assert next(csv_reader) == ["validator_node_info"]
        assert next(csv_reader) == [node.__str__()]

    os.remove(path_actions)
    os.remove(path_nodes)
    os.rmdir(directory)
    os.rmdir(base_dir)
