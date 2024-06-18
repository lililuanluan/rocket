"""CSVLogger class."""

import atexit
import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from xrpl_controller.validator_node_info import ValidatorNode

action_log_columns = [
    "timestamp",
    "action",
    "from_port",
    "to_port",
    "message_type",
    "original_data",
    "possibly_mutated_data",
]


class CSVLogger:
    """CSVLogger class which can be utilized to log to a csv file."""

    def __init__(self, filename: str, columns: list[Any], directory: str = ""):
        """Initialize CSVLogger class."""
        Path("./logs/" + directory).mkdir(parents=True, exist_ok=True)

        filename = filename if filename.endswith(".csv") else filename + ".csv"

        self.filepath = "./logs/" + directory + "/" + filename
        self.csv_file = open(self.filepath, mode="w", newline="")
        self.writer = csv.writer(self.csv_file)
        self.columns = [col.__str__ for col in columns]
        self.writer.writerow(columns)
        atexit.register(self.close)

    def close(self):
        """Close the CSV file."""
        self.csv_file.close()

    def flush(self):
        """Flush the csv file."""
        self.csv_file.flush()

    def log_row(self, row: list[Any]):
        """
        Log an arbitrary row.

        Args:
            row (list[str]): row to be logged.

        Raises:
            ValueError: if length of row is not equal to the amount of columns
        """
        if len(self.columns) != len(row):
            raise ValueError(
                f"Wrong number of column entries in the given row, required columns are: {self.columns}"
            )
        self.writer.writerow(row)

    def log_rows(self, rows: list[list[Any]]):
        """
        Log multiple arbitrary row.

        Args:
            rows (list[list[str]]): rows to be logged.

        Raises:
            ValueError: if length of any row is not equal to the amount of columns
        """
        for row in rows:
            self.log_row(row)


class ActionLogger(CSVLogger):
    """CSVLogger child class which is dedicated to handle the logging of actions."""

    def __init__(
        self,
        sub_directory: str,
        validator_node_list: list[ValidatorNode],
        filename: str | None = None,
    ):
        """Initialize ActionLogger class."""
        final_filename = filename if filename is not None else "action_log.csv"
        directory = f"action_logs/{sub_directory}"

        node_logger = CSVLogger(
            filename="node_info",
            columns=["validator_node_info"],
            directory=directory,
        )
        node_logger.log_rows([[node] for node in validator_node_list])
        node_logger.close()

        super().__init__(
            filename=final_filename,
            columns=action_log_columns,
            directory=directory,
        )

    def log_action(
        self,
        action: int,
        from_port: int,
        to_port: int,
        message_type: str,
        original_data: str,
        possibly_mutated_data: str,
        custom_timestamp: int | None = None,
    ):
        """
        Log an action according to a specific column format.

        Args:
            action: action to be logged.
            from_port: from_port of the message.
            to_port: to_port of the message.
            message_type: the message type as defined in the ripple.proto
            original_data: the message's original data.
            possibly_mutated_data: the message's possibly mutated data.
            custom_timestamp: a custom timestamp to log if desired.

        Returns:
            None
        """
        # Note: timestamp is milliseconds since epoch (January 1, 1970)
        self.writer.writerow(
            [
                int(datetime.now().timestamp() * 1000)
                if custom_timestamp is None
                else custom_timestamp,
                action,
                from_port,
                to_port,
                message_type,
                original_data,
                possibly_mutated_data,
            ]
        )
