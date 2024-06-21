"""This module contains a way to check various properties of the consensus algorithm after an iteration completes."""

from abc import abstractmethod
from typing import Any, List

from loguru import logger
from xrpl.clients import WebsocketClient
from xrpl.models import Ledger

from xrpl_controller.csv_logger import ResultLogger
from xrpl_controller.validator_node_info import ValidatorNode


class ConsensusProperty:
    """Base class for checking a consensus property."""

    @staticmethod
    @abstractmethod
    def check(
        validator_nodes: List[ValidatorNode],
        log_dir: str,
        iteration: int,
        max_ledger: int,
    ):
        """
        Abstract method for checking a consensus property.

        Args:
            validator_nodes: The list of validator nodes to check on.
            log_dir: The directory where the action log of the current iteration resides.
            iteration: The current iteration number.
            max_ledger: The configured maximum number of ledgers per iteration.

        Raises:
            NotImplementedError: The method is not implemented, a child class should implement it.
        """
        raise NotImplementedError(
            "ConsensusProperty.check is an abstract method, and cannot be called directly"
        )


class ConsistencyLivenessProperty(ConsensusProperty):
    """Class containing functionality to check Consistency and Liveness of the consensus algorithm."""

    @staticmethod
    def _fetch_ledger(ws_port: int) -> dict[str, Any] | None:
        """
        Fetch the node info from the websocket server at a specific port.

        Args:
            ws_port: the websocket server port to retrieve the node info from.

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

    @staticmethod
    def check(
        validator_nodes: List[ValidatorNode],
        log_dir: str,
        iteration: int,
        max_ledger: int,
    ):
        """
        Method for checking Consistency and Liveness.

        Args:
            validator_nodes: The list of validator nodes to check on.
            log_dir: The directory where the action log of the current iteration resides.
            iteration: The current iteration number.
            max_ledger: The configured maximum number of ledgers per iteration.
        """
        logger.info("Checking liveness and consistency...")
        result_logger = ResultLogger(log_dir, f"result-{iteration}")
        results = []

        for node in validator_nodes:
            res = ConsistencyLivenessProperty._fetch_ledger(node.ws_private.port)
            if res is None:
                logger.error(
                    f"Could not retrieve ledger from node with port: {node.peer.port}"
                )
                continue
            results.append(res)

        for i, result in enumerate(results):
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
            result_logger.log_result(
                i,
                "NOT FOUND"
                if result.get("ledger_hash") is None
                else str(result.get("ledger_hash")),
                _ledger_index,
                max_ledger,
                _close_time,
            )
        result_logger.flush()
