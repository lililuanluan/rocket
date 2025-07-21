"""This module holds functionalities to control a network of nodes."""

from typing import Any

import base58
import xrpl.models.requests
from loguru import logger
from xrpl import CryptoAlgorithm
from xrpl.clients.json_rpc_client import JsonRpcClient
from xrpl.core.keypairs import generate_seed
from xrpl.transaction import autofill_and_sign, submit
from xrpl.wallet import Wallet

from rocket_controller.helper import (
    flatten,
    parse_to_2d_list_of_ints,
    parse_to_list_of_ints,
    validate_ports_or_ids,
)
from rocket_controller.message_action import MessageAction
from rocket_controller.message_action_buffer import MessageActionBuffer
from rocket_controller.transaction_builder import TransactionBuilder
from rocket_controller.validator_node_info import ValidatorNode


class NetworkManager:
    """Class which holds and handles information related to a network of validator nodes."""

    def __init__(
        self,
        auto_parse_identical: bool | None = True,
        auto_parse_subsets: bool | None = True,
    ):
        """
        Initialize a new NetworkManager.

        Args:
            auto_parse_identical (bool, optional): Whether the strategy will perform same actions on identical messages.
            auto_parse_subsets (bool, optional): Whether the strategy will perform same actions on defined subsets.
        """
        # Initialize all necessary fields for the NetworkManager
        self.network_config: dict[str, Any] = {}
        self.validator_node_list: list[ValidatorNode] = []
        self.public_to_private_key_map: dict[str, str] = {}
        self.node_amount: int = 0
        self.port_to_id_dict: dict[int, int] = {}
        self.id_to_port_dict: dict[int, int] = {}
        self.communication_matrix: list[list[bool]] = []
        self.prev_message_action_matrix: list[list[MessageActionBuffer]] = []
        self.subsets_dict: dict[int, list[list[int]] | list[int]] = {}
        self.auto_parse_identical = auto_parse_identical
        self.auto_parse_subsets = auto_parse_subsets
        self.tx_builder = TransactionBuilder()
        self.accounts: dict[str, dict[str, str]] = {}

    def update_network(self, validator_node_list: list[ValidatorNode]):
        """
        Update the network with a list of validator nodes.

        Args:
            validator_node_list: List of validator nodes.
        """
        self.validator_node_list = validator_node_list
        self.public_to_private_key_map.clear()
        self.node_amount = len(validator_node_list)
        self.port_to_id_dict = {
            port: index
            for index, port in enumerate(
                [node.peer.port for node in validator_node_list]
            )
        }
        self.id_to_port_dict = {
            index: port
            for index, port in enumerate(
                [node.peer.port for node in validator_node_list]
            )
        }

        # Store all public-private-key pairs.
        for node in self.validator_node_list:
            decoded_pub_key = base58.b58decode(
                node.validator_key_data.validation_public_key,
                alphabet=base58.XRP_ALPHABET,
            )[1:34]
            decoded_priv_key = base58.b58decode(
                node.validator_key_data.validation_private_key,
                alphabet=base58.XRP_ALPHABET,
            )[1:33]
            self.public_to_private_key_map[decoded_pub_key.hex()] = (
                decoded_priv_key.hex()
            )

        self.partition_network(
            [[peer_id for peer_id in range(len(validator_node_list))]]
        )
        if self.auto_parse_identical:
            self.prev_message_action_matrix = [
                [
                    MessageActionBuffer(self.node_amount + 1)
                    for _ in range(self.node_amount)
                ]
                for _ in range(self.node_amount)
            ]
        if self.auto_parse_subsets:
            self.subsets_dict = {peer_id: [] for peer_id in range(self.node_amount)}

    def partition_network(self, partitions: list[list[int]]):
        """
        Set the network partition and update the communication matrix. This overrides any preceding communications.

        Args:
            partitions (list[list[int]]): List containing the network partitions (as lists of peer ID's).

        Raises:
            ValueError: If given partitions are invalid.
        """
        flattened_partitions = flatten(partitions)
        if (
            set(flattened_partitions)
            != set([peer_id for peer_id in range(len(self.validator_node_list))])
            or len(flattened_partitions) != self.node_amount
        ):
            raise ValueError(
                "The given network partition is not valid for the current network."
            )

        self.communication_matrix = [
            [False for _ in range(self.node_amount)] for _ in range(self.node_amount)
        ]

        for partition in partitions:
            for i in range(len(partition)):
                for j in range(i + 1, len(partition)):
                    peer_id_1 = partition[i]
                    peer_id_2 = partition[j]

                    self.communication_matrix[peer_id_1][peer_id_2] = True
                    self.communication_matrix[peer_id_2][peer_id_1] = True

    def connect_nodes(self, peer_id_1: int, peer_id_2: int):
        """
        Connect 2 nodes using their ID's, which allows communication between them.

        Args:
            peer_id_1 (int): Peer ID 1.
            peer_id_2 (int): Peer ID 2.

        Raises:
            ValueError: if peer_id_1 is equal to peer_id_2 or if any is negative.
        """
        validate_ports_or_ids(peer_id_1, peer_id_2)
        self.communication_matrix[peer_id_1][peer_id_2] = True
        self.communication_matrix[peer_id_2][peer_id_1] = True

    def disconnect_nodes(self, peer_id_1: int, peer_id_2: int):
        """
        Disconnect 2 nodes using their ID's, which disallows communication between them.

        Args:
            peer_id_1 (int): Peer ID 1.
            peer_id_2 (int): Peer ID 2.

        Raises:
            ValueError: if peer_id_1 is equal to peer_id_2 or if any is negative.
        """
        validate_ports_or_ids(peer_id_1, peer_id_2)
        self.communication_matrix[peer_id_1][peer_id_2] = False
        self.communication_matrix[peer_id_2][peer_id_1] = False

    def check_communication(self, peer_from_id: int, peer_to_id: int) -> bool:
        """
        Check whether 2 peers can communicate with each other using their ID's.

        Args:
            peer_from_id (int): The peer ID from where the message was sent.
            peer_to_id (int): The peer ID to where the message was sent.

        Returns:
            bool: A boolean indicating whether communication is permitted between the 2 given ID's.

        Raises:
            ValueError: if peer_from_id is equal to peer_to_id or if any is negative.
        """
        validate_ports_or_ids(peer_from_id, peer_to_id)
        return self.communication_matrix[peer_from_id][peer_to_id]

    def reset_communications(self):
        """
        Reset all communications, falling back to the network configuration.

        This method uses partition_network to rebuild the communication matrix in a correct way.
        """
        self.partition_network(
            [[peer_id for peer_id in range(len(self.validator_node_list))]]
        )

    def set_subsets_dict_entry(
        self, peer_id: int, subsets: list[list[int]] | list[int]
    ):
        """
        Set individual entries in the subsets_dict field.

        Args:
            peer_id (int): The peer ID.
            subsets (list[list[int]]): The list of subsets.

        Raises:
            ValueError: If auto_parse_subsets is False.
        """
        if not self.auto_parse_subsets:
            raise ValueError(
                "auto_parse_subsets must be set to True when calling set_subsets_dict_entry."
            )
        self.subsets_dict[peer_id] = subsets

    def set_subsets_dict(self, subsets_dict: dict[int, list[list[int]] | list[int]]):
        """
        Set the subsets_dict field, this will overwrite any previous modifications.

        Args:
            subsets_dict: The new dictionaries, a 'map' of ID's to subsets of ID's, to be used.

        Raise:
            ValueError: if auto_parse_subsets is False.
        """
        if not self.auto_parse_subsets:
            raise ValueError(
                "auto_parse_subsets must be set to True when calling set_subsets_dict."
            )

        self.subsets_dict = {peer_id: [] for peer_id in range(self.node_amount)}

        for peer_id, subsets in subsets_dict.items():
            self.set_subsets_dict_entry(peer_id, subsets)

    def set_message_action(
        self,
        peer_from_id: int,
        peer_to_id: int,
        initial_message: bytes,
        final_message: bytes,
        action: int,
    ):
        """
        Set an entry in the message_action_matrix.

        Args:
            peer_from_id: Sender peer ID.
            peer_to_id: Receiving peer ID.
            initial_message: The pre-processed message.
            final_message: The (possibly mutated) processed message
            action: The taken action

        Raises:
            ValueError: if auto_parse_identical and auto_parse_subsets are False, and if peer_from_id is equal to peer_to_id or if any is negative
        """
        if not (self.auto_parse_identical or self.auto_parse_subsets):
            raise ValueError(
                "auto_parse_subsets must be set to True when calling set_message_action."
            )

        validate_ports_or_ids(peer_from_id, peer_to_id)
        self.prev_message_action_matrix[peer_from_id][peer_to_id].add(
            MessageAction(initial_message, final_message, action)
        )

    def check_previous_message(
        self, peer_from_id: int, peer_to_id: int, message: bytes
    ) -> tuple[bool, tuple[bytes, int]]:
        """
        Parse a message automatically to a final state with an action if it was matching to the previous message.

        Example Usage (Pseudocode):
            res: (bool, (bytes, int)) = check_previous_message(id_1, id_2, message)
            if res[0] then (message, action) = res[1]
            else: ...

        Args:
            peer_from_id: Sender peer ID.
            peer_to_id: Receiving peer ID.
            message: The message to be checked for parsing.

        Returns:
            Tuple(bool, Tuple(bytes, int)): Boolean indicating success along with final message and action.

        Raises:
            ValueError: If auto_parse_identical and auto_parse_subsets are False.
        """
        if not (self.auto_parse_identical or self.auto_parse_subsets):
            raise ValueError(
                "auto_parse_subsets or auto_parse_identical must be set to True when calling check_previous_message."
            )

        return self.prev_message_action_matrix[peer_from_id][
            peer_to_id
        ].match_previous_messages(message)

    def check_subset_entry(
        self, peer_from_id: int, peer_to_id: int, message: bytes, subset: list[int]
    ) -> tuple[bool, tuple[bytes, int]]:
        """
        Check a subset for identical messages.

        Args:
            peer_from_id: Sender peer ID.
            peer_to_id: Receiving peer ID.
            message: The message to be checked for parsing.
            subset: The subset of ID's to check.

        Returns:
            A tuple indicating success along with final message and action.
        """
        # For the subset which peer_to_id is in, check whether an identical message can be found.
        # If one is found, we automatically parse it to the processed version with its action.
        if peer_to_id in subset:
            for peer_id in subset:
                if (
                    result := self.check_previous_message(
                        peer_from_id, peer_id, message
                    )
                )[0]:
                    # result is a tuple[bool, tuple[bytes, int]]
                    # The second tuple contains the processed message and an action
                    self.set_message_action(
                        peer_from_id, peer_to_id, message, result[1][0], result[1][1]
                    )
                    return result

        return False, self.check_previous_message(peer_from_id, peer_to_id, message)[1]

    def check_subsets(
        self, peer_from_id: int, peer_to_id: int, message: bytes
    ) -> tuple[bool, tuple[bytes, int]]:
        """
        Check multiple subsets for identical messages.

        Args:
            peer_from_id: Sender peer ID.
            peer_to_id: Receiving peer ID.
            message: The message to be checked for parsing.

        Returns:
            A tuple indicating success along with final message and action.

        Raises:
            ValueError: If auto_parse_identical is False.
        """
        if not self.auto_parse_subsets:
            raise ValueError(
                "auto_parse_subsets must be set to True when calling check_subsets."
            )

        # self.subsets_dict[peer_from_id] can contain a 1- or 2-dimensional integer list.
        # We first check whether the list is 2-dimensional, if so, we handle the entry accordingly.
        if len(self.subsets_dict[peer_from_id]) > 0 and isinstance(
            self.subsets_dict[peer_from_id][0], list
        ):
            # We have to parse the list to a list[list[int]] type to suppress tox.
            for subset in parse_to_2d_list_of_ints(self.subsets_dict[peer_from_id]):
                if (
                    result := self.check_subset_entry(
                        peer_from_id, peer_to_id, message, subset
                    )
                )[0]:
                    return result
            return False, self.check_previous_message(
                peer_from_id, peer_to_id, message
            )[1]
        else:
            # In this branch, we know for certain that self.subsets_dict[peer_from_id] is 1-dimensional.
            # We have to parse the list to a list[int] type to suppress tox.
            return self.check_subset_entry(
                peer_from_id,
                peer_to_id,
                message,
                parse_to_list_of_ints(self.subsets_dict[peer_from_id]),
            )

    def port_to_id(self, port: int) -> int:
        """
        Transform a port to its corresponding index.

        Args:
            port: The port of which the corresponding peer ID is needed.

        Returns:
            int: The corresponding peer ID

        Raises:
            ValueError: If port is not in port_dict.
        """
        try:
            return self.port_to_id_dict[port]
        except KeyError as err:
            raise ValueError(f"Port {port} not found in port_to_id_dict") from err

    def id_to_port(self, peer_id: int) -> int:
        """
        Transform a peer ID to its corresponding port.

        Args:
            peer_id: the peer ID of which the port is needed.

        Returns:
            The corresponding port.

        Raises:
            ValueError: If peer_id is not in port_dict.
        """
        try:
            return self.id_to_port_dict[peer_id]
        except KeyError as err:
            raise ValueError(f"peer ID {peer_id} not found in id_to_port_dict") from err

    def get_account(
            self,
            account_alias: str
            ):
        if account_alias is None or account_alias == "None":
            return None
        if account_alias not in self.accounts:
            seed = generate_seed(algorithm=CryptoAlgorithm.SECP256K1)
            wallet = Wallet.from_seed(seed=seed, algorithm=CryptoAlgorithm.SECP256K1)
            self.accounts[account_alias] = {
                'address': wallet.classic_address,
                'seed': seed
            }
            logger.info(f"Creating account {account_alias} with seed {seed} and address {wallet.classic_address}")
        return self.accounts[account_alias]

    def submit_transaction(
        self,
        peer_id: int,
        amount: int = 1_000_000_000,
        sender_account: str | None = None,
        sender_account_seed: str | None = None,
        destination_account: str | None = None,
    ):
        """
        Submit a transaction to a peer of choice.

        Args:
            peer_id: the ID of the peer which will receive the transaction.
            amount: the amount of XRP drops to be included in the transaction.
            sender_account: the account address from which to send XRP in hex.
            sender_account_seed: seed for account in SECP256K1 format in hex.
            destination_account: the account id of the destination of the transaction in hex.

        Raises:
            ValueError: if peer_id is not in id_to_port_dict.
        """
        if peer_id not in self.id_to_port_dict:
            raise ValueError(
                f"Given peer ID does not exist in the current network: {peer_id}"
            )

        rpc_address = ""
        for validator in self.validator_node_list:
            if validator.peer.port == self.id_to_port(peer_id):
                rpc_address = f"http://{validator.rpc.as_url()}/"
        tx = self.tx_builder.build_transaction(
            amount=amount,
            sender_account=sender_account,
            sender_account_seed=sender_account_seed,
            destination_account=destination_account,
        )
        client = JsonRpcClient(rpc_address)
        complete_tx = autofill_and_sign(tx, client, self.tx_builder.wallet)
        response = submit(complete_tx, client)
        # logger.info(f"Sent a transaction submission to node {peer_id}, url: {rpc_address}")
        self.tx_builder.add_transaction(complete_tx)
        return response

    def validate_transaction(self, tx_hash: str, peer_id: int):
        validator = self.validator_node_list[peer_id]
        rpc_address = f"http://{validator.rpc.as_url()}/"
        client = JsonRpcClient(rpc_address)
        tx_result = client.request(xrpl.models.requests.Tx(transaction=tx_hash))
        # logger.info(f"Validating transaction {tx_hash} response: {tx_result}")
        if tx_result.is_successful() and tx_result.result.get('validated', False):
            return True
        else:
            return False

    def get_transactions(self, ledger_seq: int | str, peer_id: int) -> (str | None, list[str] | None):
        """
        Get set of validated transactions for a certain peer and ledger sequence

        Args:
            ledger_seq: ledger sequence/index
            peer_id: peer id

        Returns:
            list of transactions or None when an error occurred
        """

        validator = self.validator_node_list[peer_id]
        rpc_address = f"http://{validator.rpc.as_url()}/"
        client = JsonRpcClient(rpc_address)
        ledger_result = client.request(xrpl.models.requests.Ledger(ledger_index=ledger_seq, transactions=True))

        # Handle null-pointers / empty values
        ledger = ledger_result.result.get('ledger', {})
        transactions = ledger.get('transactions', None)
        ledger_hash = ledger_result.result.get('ledger_hash', None)
        validated = ledger_result.result.get('validated', False)
        ledger_index = ledger_result.result.get('ledger_index', None)

        return ledger_hash, transactions, validated, ledger_index

    def get_balances(self, peer_id: int, ledger_seq: int):
        """
        Get balances of all self-created accounts (self.accounts)

        Returns:
            Dict of all accounts (alias) with their balances
        """

        validator = self.validator_node_list[peer_id]
        rpc_address = f"http://{validator.rpc.as_url()}/"
        client = JsonRpcClient(rpc_address)

        result = {}

        for alias, account in self.accounts.items():
            if alias is None or alias == 'None':
                continue
            address = account["address"]
            acc_result = client.request(xrpl.models.requests.AccountInfo(account=address, ledger_index=ledger_seq))
            result[alias] = {'address': address, 'balance': acc_result.result.get('account_data', {}).get('Balance', None)}

        return result
