"""This module contains a way to check various properties of the consensus algorithm after an iteration completes."""

from abc import abstractmethod
from typing import List

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
    def _fetch_ledger(ws_port: int):
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
        Abstract method for checking a consensus property.

        Args:
            validator_nodes: The list of validator nodes to check on.
            log_dir: The directory where the action log of the current iteration resides.
            iteration: The current iteration number.
            max_ledger: The configured maximum number of ledgers per iteration.
        """
        logger.info("Checking liveness and consistency...")
        result_logger = ResultLogger(log_dir, f"result-{iteration}")
        results = [
            ConsistencyLivenessProperty._fetch_ledger(node.ws_private.port)
            for node in validator_nodes
        ]
        for i, result in enumerate(results):
            result_logger.log_result(
                i,
                result.get("ledger_hash"),
                result.get("ledger_index"),
                max_ledger,
                result.get("close_time"),
            )
