"""Module that defines certain Iteration Types."""

import threading
from datetime import datetime, timedelta

from loguru import logger

from protos import ripple_pb2
from xrpl_controller.interceptor_manager import InterceptorManager


class IterationType:
    """Base class for defining iteration mechanisms."""

    def __init__(
        self, max_iterations: int, interceptor_manager: InterceptorManager | None = None
    ):
        """Init Iteration Type with an InterceptorManager attached."""
        self._max_iterations = max_iterations
        self._cur_iteration = 0

        self._interceptor_manager = (
            InterceptorManager() if interceptor_manager is None else interceptor_manager
        )

    def add_iteration(self):
        """Add an iteration to the iteration mechanism, stops when max_iterations is reached."""
        if self._cur_iteration < self._max_iterations:
            logger.info(f"Starting iteration {self._cur_iteration}")
            self._interceptor_manager.restart()
            self._cur_iteration += 1
        else:
            logger.info(
                f"Finished iteration {self._cur_iteration}, stopping test process..."
            )
            self._interceptor_manager.stop()

    def init_interceptor(self):
        """Wrapper method to start the interceptor for the first time (on program initialization)."""
        self._interceptor_manager.start_new()


class TimeBasedIteration(IterationType):
    """Time based iteration type, restarts the interceptor process after a certain amount of seconds."""

    def __init__(
        self,
        max_iterations: int,
        timer_seconds: int,
        interceptor_manager: InterceptorManager | None = None,
    ):
        """
        Init TimeBasedIteration with an InterceptorManager attached.

        Args:
            max_iterations: Maximum number of iterations.
            timer_seconds: the amount of seconds an iteration should take.
            interceptor_manager: InterceptorManager attached to this iteration type.
        """
        super().__init__(max_iterations, interceptor_manager)
        self._timer_seconds = timer_seconds

    def start_timer(self):
        """Starts a thread which restarts the interceptor process after a set amount of seconds."""
        timer = threading.Timer(self._timer_seconds, self.add_iteration)
        timer.start()


class LedgerBasedIteration(IterationType):
    """Ledger based iteration type, restarts the interceptor process after a certain amount of validated ledgers."""

    def __init__(
        self,
        max_iterations: int,
        max_ledger_seq: int,
        interceptor_manager: InterceptorManager | None = None,
    ):
        """
        Init LedgerBasedIteration with an InterceptorManager attached.

        Args:
            max_iterations: The amount of iterations to run the test process for.
            max_ledger_seq: The amount of ledgers to be validated in a single iteration.
            interceptor_manager: InterceptorManager attached to this iteration type.
        """
        super().__init__(max_iterations, interceptor_manager)

        self.prev_network_event = 0
        self.network_event_changes = 0
        self.ledger_seq = 0
        self.prev_validation_time = datetime.now()
        self.validation_time = timedelta()

        self._max_ledger_seq = max_ledger_seq

    def reset_values(self):
        """Reset state variables, called when interceptor is restarted."""
        self.prev_network_event = 0
        self.network_event_changes = 0
        self.ledger_seq = 0
        self.prev_validation_time = datetime.now()
        self.validation_time = timedelta()

    def update_iteration(self, status: ripple_pb2.TMStatusChange):
        """
        Update the iteration values, called when a TMStatusChange is received.

        Args:
            status: The TMStatusChange message received on the network.
        """
        if self.prev_network_event != status.newEvent:
            self.prev_network_event = status.newEvent
            self.network_event_changes += 1
            if status.ledgerSeq > self.ledger_seq:
                self.validation_time = datetime.now() - self.prev_validation_time
                self.ledger_seq = status.ledgerSeq
                self.prev_validation_time = datetime.now()
                logger.info(
                    f"Ledger {self.ledger_seq} validated, time elapsed: {self.validation_time}"
                )
            if self.ledger_seq == self._max_ledger_seq:
                self.add_iteration()
                self.reset_values()
