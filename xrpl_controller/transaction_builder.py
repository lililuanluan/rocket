"""Module with a class which is able to build a transaction."""

from xrpl import CryptoAlgorithm
from xrpl.models import Payment, Transaction
from xrpl.wallet import Wallet


class TransactionBuilder:
    """Builder for XRP Transactions."""

    def __init__(self):
        """Initialize a new TransactionBuilder."""
        # genesis_address  is the genesis account for every XRPL network.
        self.genesis_address = "rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh"
        self.genesis_seed = "snoPBrXtMeMyMHUVTgbuqAfg1SUTb"
        self.destination_account_id = "r9wRwVgL2vWVnKhTPdtxva5vdH7FNw1zPs"

        # Public and Private keys are inferred from the seed.
        self.wallet = Wallet.from_seed(
            seed=self.genesis_seed, algorithm=CryptoAlgorithm.SECP256K1
        )

        self.transactions: list[Transaction] = []
        self.tx_amount = 0

    def build_transaction(
        self,
        amount: int = 1_000_000_000,
        sender_account: str | None = None,
        sender_account_seed: str | None = None,
        destination_account: str | None = None,
    ) -> Transaction:
        """
        Build a XRPL Transaction.

        Args:
            amount: The amount of XRPL drops to be included in the transaction.
            sender_account: The account address from which to send XRP in hex.
            sender_account_seed: Seed for account in SECP256K1 format in hex.
            destination_account: The account id of the destination of the transaction in hex.

        Returns:
            Payment: A Payment object, which inherits the Transaction class.

        Raises:
            ValueError: If amount is smaller than 1_000_000_000.
        """
        if amount < 1_000_000_000:
            raise ValueError(
                f"Amount must be greater than 1_000_000_000, given amount: {amount}"
            )

        if sender_account_seed is not None:
            self.wallet = Wallet.from_seed(
                seed=sender_account_seed, algorithm=CryptoAlgorithm.SECP256K1
            )

        payment_tx = Payment(
            account=self.genesis_address if sender_account is None else sender_account,
            amount=str(amount),  # Amount in drops (1 XRP = 1,000,000 drops)
            destination=self.destination_account_id
            if destination_account is None
            else destination_account,
        )
        return payment_tx

    def add_transaction(self, transaction: Transaction):
        """
        Add a transaction to store in this builder.

        Args:
            transaction: A Transaction to add.
        """
        self.transactions.append(transaction)
        self.tx_amount += 1
