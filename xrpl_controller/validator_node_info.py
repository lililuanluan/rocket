"""Module for useful data of a validator node."""

from typing import override


class ValidatorKeyData:
    """Class that structures the data of keys of a validator node."""

    def __init__(
        self,
        status: str,
        validation_key: str,
        validation_private_key: str,
        validation_public_key: str,
        validation_seed: str,
    ):
        """
        Initializes a new ValidatorKeyData object.

        Args:
            status: return status for the creation of this data command.
            validation_key: the secret key for these validation credentials, in RFC-1751 format.
            validation_private_key: the secret key of the node itself, used in combination with the validation_seed to create this data.
            validation_public_key: the public key for these validation credentials, in the XRP Ledger's base58 encoded string format.
            validation_seed: the secret key for these validation credentials, in the XRP Ledger's base58 encoded string format.
        """
        self.status = status
        self.validation_key = validation_key
        self.validation_private_key = validation_private_key
        self.validation_public_key = validation_public_key
        self.validation_seed = validation_seed

    @override
    def __str__(self):
        return (
            f"ValidatorKeyData(status={self.status}, validation_key={self.validation_key}, "
            f"validation_private_key={self.validation_private_key}, "
            f"validation_public_key={self.validation_public_key}, "
            f"validation_seed={self.validation_seed})"
        )


class SocketAddress:
    """Class that structures the data of a socket address."""

    def __init__(self, host: str, port: int):
        """
        Initializes a new SocketAddress object.

        Args:
            host: the host address.
            port:  the port for the address.
        """
        self.host = host
        self.port = port

    def as_url(self) -> str:
        """
        Makes an URL of the SocketAddress.

        Returns:
        str: An URL as string.
        """
        return f"{self.host}:{self.port}"

    @override
    def __str__(self):
        return f"SocketAddress(host={self.host}, port={self.port})"


class ValidatorNode:
    """A class that structures the data associated with a validator node, even private information."""

    def __init__(
        self,
        peer: SocketAddress,
        ws_public: SocketAddress,
        ws_admin: SocketAddress,
        rpc: SocketAddress,
        validator_key_data: ValidatorKeyData,
    ):
        """
        Initializes a new ValidatorNode object.

        Args:
            peer: the socket address fot the Peer connection
            ws_public: the socket address for the public WebSocket connection.
            ws_admin: the socket address for the admin WebSocket connection.
            rpc: the socket address for Json-RPC requests.
            validator_key_data: the validator data of this node
        """
        self.peer = peer
        self.ws_public = ws_public
        self.ws_private = ws_admin
        self.rpc = rpc
        self.validator_key_data = validator_key_data

    @override
    def __str__(self):
        return (
            f"ValidatorNode(peer={self.peer}, ws_public={self.ws_public}, ws_private={self.ws_private}, "
            f"rpc={self.rpc}, validator_key_data={self.validator_key_data})"
        )
