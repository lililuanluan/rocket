"""This module contains an implementation to log ledger results."""

from typing import Any, List

from loguru import logger
from xrpl.clients import WebsocketClient
from xrpl.models import Ledger

from rocket_controller.csv_logger import ResultLogger
from rocket_controller.validator_node_info import ValidatorNode


class LedgerResult:
    """Class for logging ledger results."""

    def __init__(self):
        """Initialize the LedgerResult object."""
        self.result_logger: ResultLogger | None = None

    def new_result_logger(self, log_dir: str, iteration: int):
        """
        Create a new LedgerResult.

        Args:
            log_dir: The directory where the action log of the current iteration resides.
            iteration: The current iteration number.
        """
        self.result_logger = ResultLogger(
            f"{log_dir}/iteration-{iteration}", f"result-{iteration}"
        )

    def flush_and_close(self):
        """Flush and close the result logger."""
        if self.result_logger:
            self.result_logger.flush()
            self.result_logger.close()

    @staticmethod
    def _fetch_ledger(ws_port: int) -> dict[str, Any] | None:
        """
        Fetch the node info from the websocket server at a specific port.

        Args:
            ws_port: The websocket server port to retrieve the node info from.

        Returns:
            A dictionary containing the node info if available, None otherwise.
        """
        with WebsocketClient(f"ws://localhost:{ws_port}") as client:
            ledger_info = Ledger()
            ledger_response = client.request(ledger_info)
            if not ledger_response.is_successful():
                logger.error("request failed")
                return None
            if ledger_response.result is None:
                return None
            closed_ledger = ledger_response.result.get("closed")
            if closed_ledger is None:
                return None
            return closed_ledger.get("ledger")

    def log_ledger_result(
        self,
        ledger_count: int,
        goal_ledger: int,
        time_to_consensus: float,
        validator_nodes: List[ValidatorNode],
    ):
        """
        Method for logging the ledger results.

        Args:
            ledger_count: The current ledger count.
            goal_ledger: The configured maximum number of ledgers per iteration.
            time_to_consensus: The time taken to reach consensus.
            validator_nodes: The list of validator nodes to check on.
        """
        results = []

        for node in validator_nodes:
            res = self._fetch_ledger(node.ws_private.port)
            if res is None:
                logger.error(
                    f"Could not retrieve ledger from node with port: {node.peer.port}"
                )
                continue
            results.append(res)

        ledger_indexes = []
        close_times = []
        ledger_hashes = []

        for _, result in enumerate(results):
            ledger_index = result.get("ledger_index")
            close_time = result.get("close_time")

            _ledger_index = (
                -1
                if ledger_index is None
                else int(ledger_index)
                if isinstance(ledger_index, (int, float, str))
                and str(ledger_index).isdigit()
                else -1
            )

            _close_time = (
                -1
                if close_time is None
                else int(close_time)
                if isinstance(close_time, (int, float, str))
                and str(close_time).isdigit()
                else -1
            )

            _ledger_hash = (
                "NOT FOUND"
                if result.get("ledger_hash") is None
                else str(result.get("ledger_hash"))
            )

            ledger_indexes.append(_ledger_index)
            close_times.append(_close_time)
            ledger_hashes.append(_ledger_hash)

        if self.result_logger:
            self.result_logger.log_result(
                ledger_count,
                goal_ledger,
                time_to_consensus,
                close_times,
                ledger_hashes,
                ledger_indexes,
            )
