"""Tests for the TimeBasedIteration class and subclasses."""

from concurrent import futures
from datetime import datetime, timedelta
from unittest.mock import MagicMock, Mock, call, patch

import grpc

from protos import ripple_pb2
from tests.default_test_variables import node_0, node_1, status_msg_1, status_msg_2
from xrpl_controller.interceptor_manager import InterceptorManager
from xrpl_controller.iteration_type import (
    LedgerBasedIteration,
    NoneIteration,
    TimeBasedIteration,
)

validator_nodes = [node_0, node_1]


def test_ledger_based_iteration_init():
    """Tests the initialization of IterationTemplate."""
    iteration = LedgerBasedIteration(5, 10, 60)
    assert iteration._max_iterations == 5
    assert iteration._max_ledger_seq == 10
    assert iteration.cur_iteration == 0
    assert iteration._timeout_seconds == 60
    assert iteration.ledger_timeout is True
    assert iteration.ledger_seq == 1
    assert isinstance(iteration.prev_validation_time, datetime)
    assert isinstance(iteration.validation_time, timedelta)
    assert isinstance(iteration._interceptor_manager, InterceptorManager)


def test_time_based_iteration_add():
    """Tests starting new iteration of TimeBasedIteration."""
    iteration = TimeBasedIteration(
        5,
        10,
    )
    mock_interceptor_manager = Mock()
    iteration._interceptor_manager = mock_interceptor_manager
    iteration._start_timeout_timer = MagicMock()
    mock_ledger_results = Mock()
    iteration._ledger_results = mock_ledger_results
    iteration.add_iteration()

    assert iteration.cur_iteration == 1
    mock_interceptor_manager.start_new.assert_called_once()
    mock_interceptor_manager.stop.assert_called_once()
    mock_ledger_results.new_result_logger.assert_called_once()


def test_time_based_iteration_add_done():
    """Tests whether cleanup is performed properly when iterations reach maximum."""
    iteration = TimeBasedIteration(1, 10)
    mock_interceptor_manager = Mock()
    iteration._interceptor_manager = mock_interceptor_manager
    iteration._start_timeout_timer = MagicMock()
    mock_ledger_results = Mock()
    iteration._ledger_results = mock_ledger_results
    mock_spec_checker = Mock()
    iteration._spec_checker = mock_spec_checker
    grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    grpc_server.stop = MagicMock()

    iteration.set_server(grpc_server)
    iteration.add_iteration()
    iteration.add_iteration()

    mock_interceptor_manager.start_new.assert_called_once()
    assert mock_interceptor_manager.stop.call_count == 2
    mock_interceptor_manager.cleanup_docker_containers.assert_called_once()
    grpc_server.stop.assert_called_once()
    mock_ledger_results.flush_and_close.assert_called_once()
    mock_spec_checker.spec_check.assert_called_once()
    mock_spec_checker.aggregate_spec_checks.assert_called_once()


def test_time_based_iteration_add_done_no_server():
    """Tests whether cleanup is performed properly when iterations reach maximum with no server."""
    iteration = TimeBasedIteration(1, 10)
    mock_interceptor_manager = Mock()
    iteration._interceptor_manager = mock_interceptor_manager
    iteration._start_timeout_timer = MagicMock()
    iteration._ledger_results = Mock()
    iteration._spec_checker = Mock()
    grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    grpc_server.stop = MagicMock()

    # iteration.set_server(grpc_server)
    iteration.add_iteration()
    iteration.add_iteration()

    mock_interceptor_manager.start_new.assert_called_once()
    assert mock_interceptor_manager.stop.call_count == 2
    mock_interceptor_manager.cleanup_docker_containers.assert_called_once()
    grpc_server.stop.assert_not_called()


def test_time_based_iteration_update():
    """Tests updating IterationTemplate with new status change."""
    iteration = TimeBasedIteration(5, 10)
    mock_interceptor_manager = Mock()
    iteration._interceptor_manager = mock_interceptor_manager
    iteration.set_validator_nodes(validator_nodes)
    iteration._start_timeout_timer = MagicMock()
    iteration.start_timeout = MagicMock()
    iteration._ledger_results = Mock()

    iteration.on_status_change(status_msg_1)
    iteration.on_status_change(status_msg_1)

    assert iteration.ledger_seq == 2


def test_ledger_based_iteration_update_complete():
    """Tests updating IterationTemplate with new status change, which should start a new iteration."""
    iteration = LedgerBasedIteration(5, 2)
    mock_interceptor_manager = Mock()
    iteration._interceptor_manager = mock_interceptor_manager
    iteration.set_validator_nodes(validator_nodes)
    iteration._start_timeout_timer = MagicMock()
    iteration.add_iteration = MagicMock()
    iteration._reset_values = MagicMock()
    iteration._ledger_results = Mock()

    iteration.on_status_change(status_msg_1)
    iteration.on_status_change(status_msg_2)

    assert iteration.ledger_seq == 2
    iteration.add_iteration.assert_called_once()


def test_ledger_based_iteration_reset_parameters():
    """Test whether the reset_parameters function, resets the correct parameters."""
    iteration = LedgerBasedIteration(5, 10)
    mock_interceptor_manager = Mock(spec=InterceptorManager)
    iteration._interceptor_manager = mock_interceptor_manager
    iteration.add_iteration = MagicMock()
    iteration._start_timeout_timer = MagicMock()
    with patch(
        "xrpl_controller.iteration_type.threading.Timer", return_value=Mock()
    ) as mock_timer:
        iteration._timer = mock_timer.return_value
        iteration.on_status_change(status_msg_1)
        iteration._reset_values()

        mock_timer.return_value.cancel.assert_has_calls([call()])

    assert iteration._max_iterations == 5
    assert iteration._max_ledger_seq == 10

    assert iteration.ledger_seq == 1
    assert isinstance(iteration.prev_validation_time, datetime)
    assert isinstance(iteration.validation_time, timedelta)
    assert isinstance(iteration._interceptor_manager, InterceptorManager)


def test_ledger_based_iteration_reset_parameters_no_timer():
    """Test whether the reset_parameters function, resets the correct parameters without a timer defined."""
    iteration = LedgerBasedIteration(5, 10)
    mock_interceptor_manager = Mock(spec=InterceptorManager)
    iteration._interceptor_manager = mock_interceptor_manager
    iteration.add_iteration = MagicMock()
    iteration._start_timeout_timer = MagicMock()
    with patch(
        "xrpl_controller.iteration_type.threading.Timer", return_value=Mock()
    ) as mock_timer:
        iteration.on_status_change(status_msg_1)
        iteration._reset_values()

        mock_timer.return_value.cancel.assert_not_called()

    assert iteration._max_iterations == 5
    assert iteration._max_ledger_seq == 10

    assert iteration.network_event_changes == 0
    assert iteration.ledger_seq == 1
    assert isinstance(iteration.prev_validation_time, datetime)
    assert isinstance(iteration.validation_time, timedelta)
    assert isinstance(iteration._interceptor_manager, InterceptorManager)


# def test_time_based_iteration_timer():
#     """Test whether the timer function calls the add_iteration method."""
#     iteration = TimeBasedIteration(5, 0)
#     iteration.add_iteration = MagicMock()
#
#     iteration.start_timeout_timer()
#
#     iteration.add_iteration.assert_called_once()
#
#
# def test_start_timeout_timer_with_existing_timer():
#     """Test whether the start_timeout_timer function cancels the existing timer."""
#     iteration = TimeBasedIteration(max_iterations=5, timeout_seconds=0)
#
#     with patch(
#         "xrpl_controller.iteration_type.threading.Timer", return_value=Mock()
#     ) as mock_timer:
#         iteration._timer = mock_timer.return_value
#         iteration.start_timeout_timer()
#
#         mock_timer.assert_called_once()
#         mock_timer.return_value.cancel.assert_called_once()


def test_none_iteration_add():
    """Test adding an iteration with NoneIteration class."""
    iteration = NoneIteration(60)
    iteration._start_timeout_timer = MagicMock()
    assert iteration._max_iterations == 1
    assert iteration.cur_iteration == 0
    assert isinstance(iteration._interceptor_manager, InterceptorManager)

    iteration.add_iteration()
    assert iteration._max_iterations == 1
    assert iteration.cur_iteration == 1
    iteration._start_timeout_timer.assert_called_once()
    assert isinstance(iteration._interceptor_manager, InterceptorManager)


def test_timeout_timer():
    """Test whether the timer is initialized correctly."""
    iteration = LedgerBasedIteration(5, 10, ledger_timeout_seconds=15)
    iteration.add_iteration = MagicMock()

    with patch(
        "xrpl_controller.iteration_type.threading.Timer", return_value=Mock()
    ) as mock_timer:
        iteration._start_timeout_timer()

        mock_timer.return_value.cancel.assert_not_called()
        mock_timer.assert_called_with(15, iteration._timeout_reached)

    # iteration.add_iteration.assert_called_once()


def test_timeout_timer_cancel():
    """Test whether a timer is cancelled before starting a new one."""
    iteration = LedgerBasedIteration(5, 10, ledger_timeout_seconds=15)
    iteration.add_iteration = MagicMock()
    prev_timer = MagicMock()
    iteration._timer = prev_timer

    with patch(
        "xrpl_controller.iteration_type.threading.Timer", return_value=Mock()
    ) as mock_timer:
        iteration._start_timeout_timer()
        mock_timer.assert_called_with(15, iteration._timeout_reached)

    prev_timer.cancel.assert_called_once()


def test_timeout_reached():
    """Test the behavior when a timeout is reached."""
    iteration = LedgerBasedIteration(5, 10, ledger_timeout_seconds=15)
    iteration.add_iteration = MagicMock()

    iteration._timeout_reached()

    iteration.add_iteration.assert_called_once()


def test_init_time_iter():
    """Test initialization of TimeIteration class."""
    iteration = TimeBasedIteration(max_iterations=1, timeout_seconds=15)
    assert iteration._max_iterations == 1
    assert iteration.cur_iteration == 0
    assert iteration._timeout_seconds == 15

    iteration.on_status_change(ripple_pb2.TMStatusChange())


def test_none_iter():
    """Test initialization of NoneIteration class."""
    iteration = NoneIteration(60)
    assert iteration._max_iterations == 1
    assert iteration.cur_iteration == 0
    assert iteration._timeout_seconds == 60

    iteration._stop_all = MagicMock()
    iteration._terminate_server = Mock()
    iteration._timeout_reached()

    iteration._stop_all.assert_called_once()
    iteration._terminate_server.assert_called_once()
    iteration.on_status_change(ripple_pb2.TMStatusChange())


def test_reset_values_none_iter():
    """Test whether calling _reset_values does not do anything when not implemented."""
    iteration = NoneIteration(60)
    assert iteration._max_iterations == 1
    assert iteration.cur_iteration == 0
    assert iteration._timeout_seconds == 60

    iteration._reset_values()
    assert iteration._max_iterations == 1
    assert iteration.cur_iteration == 0
    assert iteration._timeout_seconds == 60


@patch("xrpl_controller.iteration_type.SpecChecker")
def test_set_log_dir(mock_spec_checker):
    """Test whether the log directory is set correctly."""
    iteration = TimeBasedIteration(5, 10)
    iteration.set_log_dir("test")
    assert iteration._log_dir == "test"
    mock_spec_checker.assert_called_once_with("test")
