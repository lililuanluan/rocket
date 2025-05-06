"""Module that defines certain Iteration Types."""

import threading
import time
from datetime import datetime
from typing import Dict, List, TypedDict

from grpc import Server
from loguru import logger

from protos import ripple_pb2
from rocket_controller.interceptor_manager import InterceptorManager
from rocket_controller.ledger_result import LedgerResult
from rocket_controller.network_manager import NetworkManager
from rocket_controller.spec_checker import SpecChecker
from rocket_controller.transaction_builder import TransactionBuilder
from rocket_controller.validator_node_info import ValidatorNode


class LedgerValidationInfo(TypedDict):
    """Information about the ledger validation."""

    seq: int
    time: datetime


class TimeBasedIteration:
    """Time Based iteration type, keeps track of time elapsed since network start."""

    def __init__(
        self,
        max_iterations: int,
        timeout_seconds: int = 60,
        ledger_timeout: bool = False,
        max_ledger_seq: int = -1,
    ):
        """
        Init Iteration Type with an InterceptorManager attached.

        Args:
            max_iterations: The maximum number of iterations to run.
            timeout_seconds: The maximum time in seconds for each iteration.
            ledger_timeout: Whether the timeout should be reset after each ledger validation, True for LedgerBasedIteration.
            max_ledger_seq: The maximum ledger sequence to validate (only for LedgerBasedIteration).
        """
        self.cur_iteration = 0
        self._ledger_results = LedgerResult()
        self._spec_checker: SpecChecker | None = None

        self._max_iterations = max_iterations
        self._server: Server | None = None
        self._network: NetworkManager | None = None
        self._timer: threading.Timer | None = None
        self._transaction_timer: threading.Timer | None = None
        self._timers: List[threading.Timer] = []
        self._timeout_seconds = timeout_seconds
        self.ledger_timeout = ledger_timeout

        self._interceptor_manager = InterceptorManager()
        self._validator_nodes: List[ValidatorNode] | None = None
        self._log_dir: str | None = None

        self._max_ledger_seq = max_ledger_seq
        self.ledger_validation_map: Dict[int, LedgerValidationInfo] = {}
        self._lock = threading.Lock()

    def _stop_all(self):
        """Stop the interceptor along with the docker containers."""
        logger.info(
            f"Finished iteration {self.cur_iteration-1}, stopping test process..."
        )
        self._interceptor_manager.stop()
        self._interceptor_manager.cleanup_docker_containers()

    def _terminate_server(self):
        """Terminate the gRPC server."""
        if self._server:
            self._server.stop(grace=1)

    def _start_timeout_timer(self):
        """Starts a timeout timer, which starts a new iteration when the timeout is reached."""
        if self._timer:
            self._timer.cancel()
        self._timer = threading.Timer(self._timeout_seconds, self._timeout_reached)
        self._timer.start()

    def _timeout_reached(self):
        """Function that is called when the timeout is reached."""
        logger.info("Timeout reached.")
        self.add_iteration()

    def _start_transactions(self):
        if self._transaction_timer:
            self._transaction_timer.cancel()
        logger.info("Starting Transaction.")
        self._transaction_timer = threading.Timer(20, self._perform_transactions)
        self._transaction_timer.start()

    def _perform_transactions(self):
        if not self._validator_nodes:
            logger.error("No validator nodes available. Cannot perform transaction.")
            return

        if not self._network:
            logger.error("Network not initialized. Cannot perform transaction.")
            return

        # Wait until at least ledger 2 is validated before attempting transactions
        if self.ledger_validation_map[1]["seq"] < 2:
            logger.info("Waiting for ledger to be available before submitting transaction...")
            self._transaction_timer = threading.Timer(2, self._perform_transactions)
            self._transaction_timer.start()
            return
        time.sleep(2)
        genesis_transactions = self._network.network_config.get('transactions', {}).get('genesis', {})
        regular_transactions = self._network.network_config.get('transactions', {}).get('regular', {})
        logger.info(
            f"Attempting to submit {len(genesis_transactions)} Genesis Transactions and {len(regular_transactions)} Regular Transactions to the network."
        )
        for tx in genesis_transactions:
            logger.info(f"Performing Genesis Transaction: {tx}")
            peer_id = tx.get('peer_id')
            amount = tx.get('amount')
            sender_account = self._network.get_account(tx.get('sender_account'))
            destination_account = self._network.get_account(tx.get('destination_account'))
            self.perform_transaction(peer_id, amount, sender_account, destination_account)
        for tx in regular_transactions:
            logger.info(f"Performing Regular Transaction: {tx}")
            peer_id = tx.get('peer_id')
            amount = tx.get('amount')
            sender_account = self._network.get_account(tx.get('sender_account'))
            destination_account = self._network.get_account(tx.get('destination_account'))
            delay = tx.get('time')
            timer = threading.Timer(delay, lambda p=peer_id, a=amount, s=sender_account, d=destination_account: self.perform_transaction(p, a, s, d))
            timer.start()
            self._timers.append(timer)

    def perform_transaction(self, peer_id: int, amount: int, sender_account: Dict[str, str], destination_account: Dict[str, str] = None):
        logger.info(f"Sending {amount} from {sender_account} to {destination_account} using peer {peer_id}...")
        try:
            self._network.submit_transaction(peer_id=peer_id, amount=amount,
                                             sender_account=sender_account.get('address') if sender_account else None,
                                             sender_account_seed=sender_account.get('seed') if sender_account else None,
                                             destination_account=destination_account.get('address') if destination_account else None)
        except Exception as e:
            logger.error(f"Error while sending transaction: {e}")
            if "Current ledger is unavailable" in str(e):
                logger.info("Current ledger is unavailable, waiting for it to become available...")
                time.sleep(1)
                self.perform_transaction(peer_id, amount, sender_account, destination_account)
                return
            elif "Transaction submission failed" in str(e):
                logger.info("Transaction submission failed, retrying...")
                time.sleep(1)
                self.perform_transaction(peer_id, amount, sender_account, destination_account)
                return
            else:
                logger.error("Transaction submission failed")
                return

    def set_server(self, server: Server):
        """
        Set the server variable to the running instance of the gRPC server.

        Args:
            server: New Server.
        """
        self._server = server


    def set_network(self, network: NetworkManager):
        self._network = network


    def set_validator_nodes(self, validator_nodes: List[ValidatorNode]):
        """
        Setter for the validator_nodes list, since it needs to be updated every iteration.

        Args:
            validator_nodes: New list of validator nodes.
        """
        self._validator_nodes = validator_nodes
        _now = datetime.now()
        self.ledger_validation_map = {
            i: {"seq": 1, "time": _now} for i in range(len(validator_nodes))
        }

    def set_log_dir(self, log_dir: str):
        """
        Setter for the log_dir variable and instantiate the SpecChecker.

        Args:
            log_dir: New log directory.
        """
        self._log_dir = log_dir
        self._spec_checker = SpecChecker(log_dir)

    def add_iteration(self):
        """Add an iteration to the iteration mechanism, stops all processes when max_iterations is reached."""
        if not self._spec_checker:
            raise ValueError("SpecChecker not initialized")
        if not self._log_dir:
            raise ValueError("Log directory not initialized")

        self.cur_iteration += 1

        # Wait for the logging threads to finish
        for t in threading.enumerate():
            if "LogLedgerResult" in t.name:
                t.join()

        if self.cur_iteration > 1:
            self._spec_checker.spec_check(self.cur_iteration - 1)
        if self.cur_iteration <= self._max_iterations:
            self._interceptor_manager.stop()
            self._ledger_results.new_result_logger(self._log_dir, self.cur_iteration)
            logger.info(f"Starting iteration {self.cur_iteration}")
            self._interceptor_manager.start_new()
            self._start_timeout_timer()
            self._start_transactions()
        else:
            self._stop_all()
            self._spec_checker.aggregate_spec_checks()
            self._terminate_server()

    def _reset_values(self):
        """Reset state variables, called when interceptor is restarted."""
        logger.debug("Iteration complete, Resetting state variables...")
        if self._timer:
            self._timer.cancel()
        self._timer = None
        if self._transaction_timer:
            self._transaction_timer.cancel()
        for t in self._timers:
            if t:
                t.cancel()
        self._timers = []
        self._transaction_timer = None
        self.ledger_validation_map = {}
        # TODO Network should not reset here!
        self._network.accounts = {}
        self._network.tx_builder = TransactionBuilder()

    def on_status_change(
        self, status: ripple_pb2.TMStatusChange, from_id: int, to_id: int
    ):
        """
        Update the iteration values, called when a TMStatusChange is received.

        When ledger_timout is True also reset the timeout when a new ledger gets validated.

        Args:
            status: The TMStatusChange message received on the network.
            from_id: The ID of the node that sent the status change message.
            to_id: The ID of the node that received the status change message.
        """
        if not self._validator_nodes:
            raise ValueError("Validator nodes not initialized.")

        with self._lock:
            # Check whether the event contains an accepted ledger which is exactly 1 sequence no. more than the prev ledger.
            if (
                status.newEvent == 1
                and status.ledgerSeq > self.ledger_validation_map[from_id]["seq"]
            ):
                self.ledger_validation_map[from_id]["seq"] = status.ledgerSeq
                _now = datetime.now()
                _validation_time = _now - self.ledger_validation_map[from_id]["time"]
                self.ledger_validation_map[from_id]["time"] = _now
                # At least one node has validated a new ledger, we can reset the timeout.
                if self.ledger_timeout:
                    self._start_timeout_timer()

                logger.info(
                    f"Node {from_id} validated ledger {self.ledger_validation_map[from_id]['seq']} in {_validation_time}"
                )
                t = threading.Thread(
                    name=f"LogLedgerResult-{from_id}-{self.ledger_validation_map[from_id]['seq']}",
                    target=self._ledger_results.log_ledger_result,
                    args=(
                        from_id,
                        self.ledger_validation_map[from_id]["seq"],
                        self._max_ledger_seq,
                        _validation_time.total_seconds(),
                        self._validator_nodes,
                    ),
                )
                t.start()

            if self._max_ledger_seq != -1 and all(
                entry["seq"] >= self._max_ledger_seq
                for entry in self.ledger_validation_map.values()
            ):
                self._reset_values()
                self.add_iteration()

    def get_ledger_sequence(self, node_id: int) -> int:
        """
        Get the current latest ledger sequence for a given node ID.

        Args:
            node_id: ID of the node to get the ledger sequence for.

        Returns:
            The current latest ledger sequence for the given node ID.

        Raises:
            ValueError: If the node ID is not found in the ledger validation map.
        """
        if node_id not in self.ledger_validation_map:
            raise ValueError(f"Node {node_id} not found in ledger validation map.")
        return self.ledger_validation_map[node_id]["seq"]


class LedgerBasedIteration(TimeBasedIteration):
    """Ledger Based iteration type, able to keep track of validated ledgers."""

    def __init__(
        self,
        max_iterations: int,
        max_ledger_seq: int = 10,
        ledger_timeout_seconds: int = 60,
    ):
        """
        Init the TimeIteration class with a specified timeout in seconds.

        Args:
            max_iterations: Maximum iterations.
            max_ledger_seq: Maximum ledger sequence.
            ledger_timeout_seconds: Timeout value for validating a new ledger.
        """
        super().__init__(
            max_iterations=max_iterations,
            timeout_seconds=ledger_timeout_seconds,
            ledger_timeout=True,
            max_ledger_seq=max_ledger_seq,
        )


class NoneIteration(TimeBasedIteration):
    """
    Iteration Type used for local testing purposes.

    It starts the controller as its separate entity without iterations,
    so you could run the interceptor separately as well.
    """

    def __init__(self, timeout_seconds: int = 300):
        """
        Init the NoneIteration class with a specified timeout in seconds.

        Args:
            timeout_seconds: Timeout for validating a new ledger.
        """
        super().__init__(max_iterations=1, timeout_seconds=timeout_seconds)

    def _timeout_reached(self):
        """Overrides _timeout_reached to stop the whole process after timeout completes."""
        logger.info("Final time reached.")
        self._stop_all()
        self._terminate_server()

    def add_iteration(self, max_ledger_seq: int = -1):
        """
        Override the add_iteration function to prevent the interceptor subprocess from starting.

        Args:
            max_ledger_seq: Unused argument, required for the override.
        """
        self._start_timeout_timer()
        self.cur_iteration += 1

    def _reset_values(self):
        """Do nothing when called, needed to satisfy abstract base class constraints."""
        pass

    def on_status_change(
        self, status: ripple_pb2.TMStatusChange, from_id: int, to_id: int
    ):
        """Override the method since none iteration does not need to keep track of ledgers."""
        pass

    def set_log_dir(self, log_dir: str):
        """Override the method since none iteration does not need do any spec checking."""
        pass
