"""This module contains an implementation to log ledger results."""

from time import sleep
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

    @staticmethod
    def _fetch_ledger(
        ws_port: int, ledger_seq: int, retries: int = 3
    ) -> dict[str, Any] | None:
        """
        Fetch the node info from the websocket server at a specific port.

        Args:
            ws_port: The websocket server port to retrieve the node info from.
            ledger_seq: The ledger sequence number to fetch.
            retries: The number of retries to attempt if the request fails (especially for early calls the node is not yet ready).

        Returns:
            A dictionary containing the node info if available, None otherwise.
        """
        with WebsocketClient(f"ws://localhost:{ws_port}") as client:
            ledger_info = Ledger(ledger_index=ledger_seq)
            ledger_response = client.request(ledger_info)
            if not ledger_response.is_successful():
                if retries > 0:
                    sleep(5)
                    return LedgerResult._fetch_ledger(ws_port, ledger_seq, retries - 1)
                logger.error(
                    f"Could not fetch ledger {ledger_seq} from port {ws_port}."
                )
                logger.debug(f"Response from {ws_port}:\n{ledger_response}")
                return None
            return ledger_response.result.get("ledger")

    def log_ledger_result(
        self,
        node_id: int,
        ledger_seq: int,
        goal_ledger: int,
        time_to_consensus: float,
        validator_nodes: List[ValidatorNode],
    ):
        """
        Method for logging the ledger results.

        Args:
            node_id: The ID of the node to log the ledger result for.
            ledger_seq: The current ledger count.
            goal_ledger: The configured maximum number of ledgers per iteration.
            time_to_consensus: The time taken to reach consensus.
            validator_nodes: The list of validator nodes to check on.
        """
        node = validator_nodes[node_id]
        result = self._fetch_ledger(node.ws_private.port, ledger_seq)
        if result is None:
            logger.error(f"Could not retrieve ledger from node {node_id}")
            return

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
            if isinstance(close_time, (int, float, str)) and str(close_time).isdigit()
            else -1
        )

        _ledger_hash = (
            "NOT FOUND"
            if result.get("ledger_hash") is None
            else str(result.get("ledger_hash"))
        )

        if not self.result_logger:
            logger.error("No result logger configured")
            return

        self.result_logger.log_result(
            node_id,
            ledger_seq,
            goal_ledger,
            time_to_consensus,
            _close_time,
            _ledger_hash,
            _ledger_index,
        )
