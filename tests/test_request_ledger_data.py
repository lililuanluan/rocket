"""Test request_ledger_data.py."""

import unittest
from unittest.mock import patch
import io

from xrpl_controller import request_ledger_data
from xrpl_controller.validator_node_info import (
    ValidatorNode,
    SocketAddress,
    ValidatorKeyData,
)

node = ValidatorNode(
    SocketAddress("test_peer", 10),
    SocketAddress("test-ws-pub", 20),
    SocketAddress("test-ws-adm", 30),
    SocketAddress("test-rpc", 40),
    ValidatorKeyData("status", "key", "K3Y", "PUB", "T3ST"),
)


class TestRequestLedgerData(unittest.TestCase):
    """Class to set up test environment."""

    @patch("sys.stdout", new_callable=io.StringIO)
    def test_store_validator_node_info(self, mock_stdout):
        """Test the store_validator_node_info function and checking its side effects."""
        # Call the function that prints to console
        request_ledger_data.store_validator_node_info([node])

        # Get the printed output
        printed_output = mock_stdout.getvalue()

        # Assert the expected output
        self.assertEqual(printed_output, f"Stored validator node info: {[node]}\n")
        assert request_ledger_data.validator_node_list_store == [node]
