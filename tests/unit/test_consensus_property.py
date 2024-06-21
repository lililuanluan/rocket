"""Test cases for the consensus_property module."""

from unittest.mock import MagicMock, call, patch

import pytest
from xrpl.models import Ledger

from tests.unit.test_strategy import node_0, node_1
from xrpl_controller.consensus_property import (
    ConsensusProperty,
    ConsistencyLivenessProperty,
)

mock_response = {"ledger_hash": "hash123", "ledger_index": 3, "close_time": 1234}


def test_parent_class_exception():
    """Check whether calling check on the base class raises an exception."""
    with pytest.raises(NotImplementedError):
        ConsensusProperty.check([], "test", 0, 0)


@patch("xrpl_controller.consensus_property.WebsocketClient")
def test_fetch_ledger(ws_client):
    """Check whether fetching the ledger API is implemented correctly."""
    ws_client().__enter__().request.return_value = MagicMock()
    ws_client().__enter__().request().result.get("closed").return_value = "closed_resp"
    ws_client().__enter__().request().result.get().get().return_value = "ledger_resp"

    ConsistencyLivenessProperty._fetch_ledger(0)

    ws_client().__enter__().request.assert_called_with(Ledger())


@patch("xrpl_controller.consensus_property.WebsocketClient")
def test_fetch_ledger_unsuccessful(ws_client):
    """Test whether unsuccessful results cause the function to return None."""
    ws_client().__enter__().request.return_value = MagicMock()
    ws_client().__enter__().request(Ledger()).is_successful.return_value = False
    # ws_client().__enter__().request(Ledger()).result = None
    # ws_client().__enter__().request(Ledger()).result.get("closed").return_value = None

    res = ConsistencyLivenessProperty._fetch_ledger(0)

    ws_client().__enter__().request.assert_called_with(Ledger())
    assert res is None


@patch("xrpl_controller.consensus_property.WebsocketClient")
def test_fetch_ledger_result_none(ws_client):
    """Test whether None result, returns None."""
    ws_client().__enter__().request.return_value = MagicMock()
    ws_client().__enter__().request(Ledger()).is_successful.return_value = True
    ws_client().__enter__().request(Ledger()).result = None
    # ws_client().__enter__().request(Ledger()).result.get("closed").return_value = None

    res = ConsistencyLivenessProperty._fetch_ledger(0)

    ws_client().__enter__().request.assert_called_with(Ledger())
    assert res is None


@patch("xrpl_controller.consensus_property.WebsocketClient")
def test_fetch_ledger_result_ledger_none(ws_client):
    """Test when get returns None, the function returns None."""
    ws_client().__enter__().request.return_value = MagicMock()
    ws_client().__enter__().request(Ledger()).is_successful.return_value = True
    ws_client().__enter__().request(Ledger()).result = MagicMock()
    ws_client().__enter__().request(Ledger()).result.get.return_value = None

    res = ConsistencyLivenessProperty._fetch_ledger(0)

    ws_client().__enter__().request.assert_called_with(Ledger())
    assert res is None


@patch("xrpl_controller.consensus_property.ResultLogger")
def test_check_liveness_consistency(logger_mock):
    """Test whether the logger is called correctly."""
    ConsistencyLivenessProperty._fetch_ledger = MagicMock(return_value=mock_response)
    ConsistencyLivenessProperty.check([node_0, node_1], "test", 0, 4)

    ConsistencyLivenessProperty._fetch_ledger.assert_has_calls(
        calls=[call(30), call(31)]
    )
    logger_mock().log_result.assert_has_calls(
        calls=[call(0, "hash123", 3, 4, 1234), call(1, "hash123", 3, 4, 1234)]
    )
