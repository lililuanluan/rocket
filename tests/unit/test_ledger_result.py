"""Test cases for the consensus_property module."""

from unittest.mock import MagicMock, Mock, call, patch

from xrpl.models import Ledger

from rocket_controller.ledger_result import LedgerResult
from tests.default_test_variables import node_0, node_1

mock_response = {"ledger_hash": "hash123", "ledger_index": 3, "close_time": 1234}


def test_init():
    """Test whether the object is initialized correctly."""
    ledger_result = LedgerResult()

    assert ledger_result.result_logger is None


@patch("rocket_controller.ledger_result.ResultLogger", return_value=Mock())
def test_new_result_logger(mock_logger):
    """Test whether the new_result_logger function works correctly."""
    iteration = 1
    ledger_result = LedgerResult()
    ledger_result.new_result_logger("test", iteration)

    assert ledger_result.result_logger is not None
    mock_logger.assert_called_with(f"test/iteration-{iteration}", "result-1")


@patch("rocket_controller.ledger_result.ResultLogger")
@patch("rocket_controller.ledger_result.WebsocketClient")
def test_fetch_ledger(ws_client, mock_logger):
    """Check whether fetching the ledger API is implemented correctly."""
    ws_client().__enter__().request.return_value = MagicMock()
    ws_client().__enter__().request().result.get("closed").return_value = "closed_resp"
    ws_client().__enter__().request().result.get().get().return_value = "ledger_resp"

    ledger_result = LedgerResult()
    ledger_result._fetch_ledger(0)

    ws_client().__enter__().request.assert_called_with(Ledger())


@patch("rocket_controller.ledger_result.ResultLogger")
@patch("rocket_controller.ledger_result.WebsocketClient")
def test_fetch_ledger_unsuccessful(ws_client, mock_logger):
    """Test whether unsuccessful results cause the function to return None."""
    ws_client().__enter__().request.return_value = MagicMock()
    ws_client().__enter__().request(Ledger()).is_successful.return_value = False
    # ws_client().__enter__().request(Ledger()).result = None
    # ws_client().__enter__().request(Ledger()).result.get("closed").return_value = None

    ledger_result = LedgerResult()
    res = ledger_result._fetch_ledger(0)

    ws_client().__enter__().request.assert_called_with(Ledger())
    assert res is None


@patch("rocket_controller.ledger_result.ResultLogger")
@patch("rocket_controller.ledger_result.WebsocketClient")
def test_fetch_ledger_result_none(ws_client, mock_logger):
    """Test whether None result, returns None."""
    ws_client().__enter__().request.return_value = MagicMock()
    ws_client().__enter__().request(Ledger()).is_successful.return_value = True
    ws_client().__enter__().request(Ledger()).result = None
    # ws_client().__enter__().request(Ledger()).result.get("closed").return_value = None

    ledger_result = LedgerResult()
    res = ledger_result._fetch_ledger(0)

    ws_client().__enter__().request.assert_called_with(Ledger())
    assert res is None


@patch("rocket_controller.ledger_result.ResultLogger")
@patch("rocket_controller.ledger_result.WebsocketClient")
def test_fetch_ledger_result_ledger_none(ws_client, mock_logger):
    """Test when get returns None, the function returns None."""
    ws_client().__enter__().request.return_value = MagicMock()
    ws_client().__enter__().request(Ledger()).is_successful.return_value = True
    ws_client().__enter__().request(Ledger()).result = MagicMock()
    ws_client().__enter__().request(Ledger()).result.get.return_value = None

    ledger_result = LedgerResult()
    res = ledger_result._fetch_ledger(0)

    ws_client().__enter__().request.assert_called_with(Ledger())
    assert res is None


@patch("rocket_controller.ledger_result.ResultLogger")
def test_log_ledger_result(logger_mock):
    """Test whether the logger is called correctly."""
    ledger_result = LedgerResult()
    ledger_result.new_result_logger("test", 1)
    ledger_result._fetch_ledger = MagicMock(return_value=mock_response)
    ledger_result.log_ledger_result(1, 5, 3.00, [node_0, node_1])

    ledger_result._fetch_ledger.assert_has_calls(calls=[call(30), call(31)])
    logger_mock().log_result.assert_has_calls(
        calls=[call(1, 5, 3.00, [1234, 1234], ["hash123", "hash123"], [3, 3])]
    )


@patch("rocket_controller.ledger_result.ResultLogger")
def test_log_ledger_result_err(logger_mock):
    """Test whether the logger is called correctly."""
    ledger_result = LedgerResult()
    ledger_result.new_result_logger("test", 1)
    ledger_result._fetch_ledger = MagicMock(return_value=None)

    ledger_result.log_ledger_result(1, 5, 3.00, [node_0, node_1])

    ledger_result._fetch_ledger.assert_has_calls(calls=[call(30), call(31)])
    logger_mock().log_result.assert_has_calls(calls=[call(1, 5, 3.0, [], [], [])])


def test_close_and_flush():
    """Test whether the close_and_flush function works correctly."""
    ledger_result = LedgerResult()
    ledger_result.result_logger = MagicMock()

    ledger_result.flush_and_close()

    ledger_result.result_logger.flush.assert_called_once()
    ledger_result.result_logger.close.assert_called_once()

    ledger_result.result_logger = None
    ledger_result.flush_and_close()

    assert ledger_result.result_logger is None


def test_log_ledger_result_none_result_logger():
    """Test whether the log_ledger_result function works correctly when result_logger is None."""
    ledger_result = LedgerResult()
    ledger_result._fetch_ledger = MagicMock(return_value=mock_response)
    ledger_result.log_ledger_result(1, 5, 3.00, [node_0, node_1])

    assert ledger_result.result_logger is None
