from abc import abstractmethod
from typing import List

from loguru import logger
from xrpl.clients import WebsocketClient
from xrpl.models import Ledger

from xrpl_controller.csv_logger import ResultLogger
from xrpl_controller.validator_node_info import ValidatorNode


class ConsensusProperty:
    @staticmethod
    @abstractmethod
    def check(validator_nodes: List[ValidatorNode]):
        raise NotImplementedError(
            "ConsensusProperty.check is an abstract method, and cannot be called directly"
        )


class ConsistencyProperty(ConsensusProperty):
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
    def check(validator_nodes: List[ValidatorNode]):
        result_logger = ResultLogger("test", "test")
        results = [
            ConsistencyProperty._fetch_ledger(node.ws_private.port)
            for node in validator_nodes
        ]
        for i, result in enumerate(results):
            result_logger.log_result(
                i,
                result.get("ledger_hash"),
                result.get("ledger_index"),
                result.get("close_time"),
            )


class LivenessProperty(ConsensusProperty):
    @staticmethod
    def check(validator_nodes: List[ValidatorNode]):
        # if this method is called, it always indicates a failure. Can you give me any ideas to refactor this class
        # hierarchy which improves the logic of naming
        pass
