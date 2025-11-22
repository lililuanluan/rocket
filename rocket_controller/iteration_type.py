"""Module that defines certain Iteration Types."""

import threading
import os
import subprocess
from datetime import datetime
from typing import Any, Dict, List, TypedDict, Iterable

from grpc import Server
from loguru import logger

from protos import ripple_pb2
from rocket_controller.interceptor_manager import InterceptorManager
from rocket_controller.ledger_result import LedgerResult
from rocket_controller.spec_checker import SpecChecker
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
        strategy_stopper = None # func in strategy to stop ws subscriber or other things
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
        self._timer: threading.Timer | None = None
        self._timeout_seconds = timeout_seconds
        self.ledger_timeout = ledger_timeout

        self._interceptor_manager = InterceptorManager()
        self._validator_nodes: List[ValidatorNode] | None = None
        self._log_dir: str | None = None

        self._max_ledger_seq = max_ledger_seq
        self.ledger_validation_map: Dict[int, LedgerValidationInfo] = {}
        self.ledger_validation_history: Dict[int, Dict[int, Dict]] = {} # node -> {seq -> {seq, time, deltatime}}
        self._lock = threading.Lock()
        # Set of byzantine node ids to exclude from spec checks (populated via set_log_dir)
        self._byzantine_nodes: set[int] = set()
        self.strategy_stopper = strategy_stopper

    def _stop_all(self):
        """Stop the interceptor along with the docker containers."""
        logger.info(
            f"Finished iteration {self.cur_iteration-1}, stopping test process..."
        )
        self.strategy_stopper() if self.strategy_stopper else None
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

    def set_server(self, server: Server):
        """
        Set the server variable to the running instance of the gRPC server.

        Args:
            server: New Server.
        """
        self._server = server

    def set_validator_nodes(self, validator_nodes: List[ValidatorNode]):
        """
        Setter for the validator_nodes list, since it needs to be updated every iteration.

        Args:
            validator_nodes: New list of validator nodes.
        """
        with self._lock:
            # this may race with on_status_change; ensure consistent state
            _now = datetime.now()
            self.ledger_validation_map = {
                i: {"seq": 1, "time": _now} for i in range(len(validator_nodes))
            }
            self.ledger_validation_history = {i: {} for i in range(len(validator_nodes))}
            self._validator_nodes = validator_nodes

    def set_log_dir(self, log_dir: str, byzantine_node_ids: Iterable[int] | None = None):
        """
        Setter for the log_dir variable and instantiate the SpecChecker.

        Args:
            log_dir: New log directory.
        """
        self._log_dir = log_dir
        # Record byzantine/excluded node ids for later spec checks
        self._byzantine_nodes = set(byzantine_node_ids) if byzantine_node_ids is not None else set()
        self._spec_checker = SpecChecker(log_dir)

    def add_iteration(self):
        """Add an iteration to the iteration mechanism, stops all processes when max_iterations is reached."""
        if not self._spec_checker:
            raise ValueError("SpecChecker not initialized")
        if not self._log_dir:
            raise ValueError("Log directory not initialized")
        logger.debug("Iteration complete, Adding iteration...")

        self.cur_iteration += 1

        # Wait for the logging threads to finish
        for t in threading.enumerate():
            if "LogLedgerResult" in t.name:
                t.join()

        if self.cur_iteration > 1:
            # Before running spec checks for the previous iteration, attempt to
            # resolve any pending ledger fetch failures so spec_check can see
            # as much data as possible. This is best-effort and will not raise.
            try:
                prev_iter = self.cur_iteration - 1
                # Prefer the ledger_result's configured logger directory if present
                try:
                    summary = self._ledger_results.retry_pending()
                    logger.info(
                        f"Retried pending ledgers for iteration {prev_iter}: {summary}"
                    )
                except Exception:
                    logger.exception("Error while retrying pending ledgers before spec check")
            except Exception:
                # Ignore any issues here; spec_check should still run.
                pass

            # Pass the configured byzantine node ids (if any) so the spec checker
            # can exclude them when computing agreement/termination.
            self._spec_checker.spec_check(self.cur_iteration - 1, exclude_node_ids=self._byzantine_nodes)

            # Pull logs from each validator node for the previous iteration
            if self._validator_nodes:
                for i, node in enumerate(self._validator_nodes):
                    container_name = f"validator_{i}"
                    log_file_path = os.path.join("./logs/" + self._log_dir, f"iteration-{self.cur_iteration - 1}", "validator_logs", f"validator_{i}_log.txt")
                    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
                    try:
                        with open(log_file_path, 'w') as f:
                            subprocess.run(['docker', 'logs', container_name], stdout=f, stderr=f, check=True, text=True)
                    except subprocess.CalledProcessError as e:
                        logger.error(f"Failed to get logs for {container_name}: {e}")
                    except Exception as e:
                        logger.error(f"Error saving logs for {container_name}: {e}")
        if self.cur_iteration <= self._max_iterations:
            self._interceptor_manager.stop()
            self._ledger_results.new_result_logger(self._log_dir, self.cur_iteration)
            logger.info(f"Starting iteration {self.cur_iteration}")
            self._interceptor_manager.start_new()
            self._start_timeout_timer()
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
        self.ledger_validation_map = {}

    def request_all_validated_ledgers(self):
        logger.info("Requesting all validated ledgers from validator nodes...")
        

        # enumerate over validator nodes safely
        if not self._validator_nodes:
            return
        for node_idx, _ in enumerate(self._validator_nodes):
            for seq in range(1, self._max_ledger_seq + 1):
                node_history = self.ledger_validation_history.get(node_idx, {})
                entry = node_history.get(seq)
                if entry and entry.get("deltatime"):
                    # deltatime is expected to be a timedelta
                    try:
                        ttc = entry["deltatime"].total_seconds()
                    except Exception:
                        # Fallback if deltatime is present but not a timedelta
                        try:
                            ttc = float(entry["deltatime"])
                        except Exception:
                            ttc = 0.0
                else:
                    # No history available for this seq; use 0.0 as conservative default
                    ttc = 0.0
                t = threading.Thread(
                    name=f"LogLedgerResult-{node_idx}-{seq}",
                    target=self._ledger_results.log_ledger_result,
                    args=(
                        node_idx,
                        seq,
                        self._max_ledger_seq,
                        ttc,
                        self._validator_nodes,
                    ),
                )
                t.start()            

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
            # Edge case: if the lock from a previous iteration gets released during a new iteration (when transitioning)
            # return to prevent logging anything.
            if not self._validator_nodes:
                return
            # Check whether the event contains an accepted ledger which is exactly 1 sequence no. more than the prev ledger.
            if (
                # status.newEvent == 1
                status.newEvent == ripple_pb2.neCLOSING_LEDGER
                and self._max_ledger_seq >= status.ledgerSeq > self.ledger_validation_map[from_id]["seq"]
            ):
                if status.ledgerSeq != self.ledger_validation_map[from_id]["seq"] + 1:
                    logger.warning(f"Node {from_id} validated non-consecutive ledger {status.ledgerSeq} (previous: {self.ledger_validation_map[from_id]['seq']})")
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

                self.ledger_validation_history.setdefault(from_id, {})
                self.ledger_validation_history[from_id][status.ledgerSeq] = {
                    "seq": self.ledger_validation_map[from_id]["seq"],
                    "time": _now,
                    "deltatime": _validation_time,
                }
                # t = threading.Thread(
                #     name=f"LogLedgerResult-{from_id}-{self.ledger_validation_map[from_id]['seq']}",
                #     target=self._ledger_results.log_ledger_result,
                #     args=(
                #         from_id,
                #         self.ledger_validation_map[from_id]["seq"],
                #         self._max_ledger_seq,
                #         _validation_time.total_seconds(),
                #         self._validator_nodes,
                #     ),
                # )
                # t.start()

            if self._max_ledger_seq == -1:
                # Return if the IterationType is time-based.
                return

            cur_ledger_infos = self.ledger_validation_map.values()
            if cur_ledger_infos and all(
                entry["seq"] >= self._max_ledger_seq
                for node_id, entry in self.ledger_validation_map.items()
                if node_id not in self._byzantine_nodes
            ):
                self._reset_values()
                # request after timers are reset
                self.request_all_validated_ledgers() 
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

    def get_ledger_sequence_cur_max(self) -> int:
        # Return the maximum ledger sequence among non-byzantine nodes.
        if not self.ledger_validation_map:
            return 0
        seqs = [
            info["seq"] for node_id, info in self.ledger_validation_map.items()
            if node_id not in self._byzantine_nodes
        ]
        return max(seqs) if seqs else 0


class LedgerBasedIteration(TimeBasedIteration):
    """Ledger Based iteration type, able to keep track of validated ledgers."""

    def __init__(
        self,
        max_iterations: int,
        max_ledger_seq: int = 10,
        ledger_timeout_seconds: int = 60,
        strategy_stopper = None # func in strategy to stop ws subscriber or other things
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
            strategy_stopper=strategy_stopper
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
