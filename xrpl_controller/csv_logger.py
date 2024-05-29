"""CSVLogger class."""

from datetime import datetime
from pathlib import Path
import csv
from typing import Any

from xrpl_controller.core import MAX_U32

action_log_columns = ["timestamp", "action", "from_port", "to_port", "data"]


class CSVLogger:
    """CSVLogger class which can be utilized to log to a csv file."""

    def __init__(self, filename: str, columns: list[Any], directory: str = ""):
        """Initialize CSVLogger class."""
        Path("./logs/" + directory).mkdir(parents=True, exist_ok=True)
        self.filepath = (
            "./logs/" + directory + "/" + filename
            if filename.endswith(".csv")
            else filename + ".csv"
        )
        self.csv_file = open(self.filepath, mode="w", newline="")
        self.writer = csv.writer(self.csv_file)
        self.columns = [col.__str__ for col in columns]
        self.writer.writerow(columns)

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
            row (list[str]): row.
        """
        if len(self.columns) != len(row):
            raise ValueError(
                f"Wrong number of column entries in the given row, required columns are: {self.columns}"
            )
        self.writer.writerow(row)


class ActionLogger(CSVLogger):
    """CSVLogger child class which is dedicated to handle the logging of actions."""

    def __init__(self):
        """Initialize ActionLogger class."""
        filename = f"action_log_{datetime.now().strftime('%Y_%m_%d_%Hh%Mm')}.csv"
        super().__init__(filename, action_log_columns, directory="action_logs")

    def log_action(self, action: int, from_port: int, to_port: int, data: bytes):
        """
        Log an action according to a specific column format.

        Args:
            action (int): Action.
            from_port (int): Port of sending peer.
            to_port (int): Port of receiving peer.
            data (bytes): Data bytes.
        """
        formatted_action = (
            "send"
            if action == 0
            else "drop"
            if action == MAX_U32
            else f"delay:{action}ms"
        )

        self.writer.writerow(
            [
                datetime.now(),
                formatted_action,
                from_port,
                to_port,
                data.hex(),
            ]
        )
