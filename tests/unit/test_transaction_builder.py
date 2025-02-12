"""Tests for TransactionBuilder."""

import pytest

from rocket_controller.transaction_builder import TransactionBuilder


def test_init():
    """Test the __init__ method."""
    builder = TransactionBuilder()
    assert builder.genesis_address == "rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh"
    assert builder.genesis_seed == "snoPBrXtMeMyMHUVTgbuqAfg1SUTb"
    assert builder.destination_account_id == "r9wRwVgL2vWVnKhTPdtxva5vdH7FNw1zPs"
    assert (
        builder.wallet.public_key
        == "0330E7FC9D56BB25D6893BA3F317AE5BCF33B3291BD63DB32654A313222F7FD020"
    )
    assert (
        builder.wallet.private_key
        == "001ACAAEDECE405B2A958212629E16F2EB46B153EEE94CDD350FDEFF52795525B7"
    )
    assert builder.transactions == []
    assert builder.tx_amount == 0


def test_build_transaction():
    """Test the build_transaction method."""
    builder = TransactionBuilder()
    tx = builder.build_transaction(amount=1000000000)
    assert tx.account == builder.genesis_address

    # The blob contains the remaining addresses and the amount, but encoded.
    assert (
        tx.blob()
        == "120000220000000061400000003B9ACA0073008114B5F762798A53D543A014CAF8B297CFF8F2F937E883145988EBB744055F4E8BDC7F67FD53EB9FCF961DC0"
    )


def test_build_transaction_2():
    """Test the build_transaction method."""
    builder = TransactionBuilder()
    tx = builder.build_transaction(
        amount=1000000000,
        sender_account="rHb9CJAWyB4rj91VRWn96DkukG4bwdtyTh",
        sender_account_seed="snoPBrXtMeMyMHUVTgbuqAfg1SUTb",
        destination_account="r9wRwVgL2vWVnKhTPdtxva5vdH7FNw1zPs",
    )
    assert tx.account == builder.genesis_address

    # The blob contains the remaining addresses and the amount, but encoded.
    assert (
        tx.blob()
        == "120000220000000061400000003B9ACA0073008114B5F762798A53D543A014CAF8B297CFF8F2F937E883145988EBB744055F4E8BDC7F67FD53EB9FCF961DC0"
    )


def test_invalid_amount():
    """Test out-point and in-point of the build_transaction method."""
    with pytest.raises(ValueError):
        TransactionBuilder().build_transaction(amount=1000000000 - 1)

    # This should not raise an exception.
    TransactionBuilder().build_transaction(amount=1000000001)


def test_add_tx():
    """Test the add_transaction method."""
    builder = TransactionBuilder()
    tx = builder.build_transaction(amount=1000000000)

    builder.add_transaction(tx)
    assert builder.transactions == [tx]
    assert builder.tx_amount == 1
