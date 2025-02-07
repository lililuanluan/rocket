"""Tests for Encoding, Decoding and Signing a packet."""

import base58
import pytest
from google.protobuf.message import EncodeError

from protos import packet_pb2, ripple_pb2
from protos.ripple_pb2 import TMProposeSet
from rocket_controller.encoder_decoder import (
    DecodingNotSupportedError,
    PacketEncoderDecoder,
)


# TODO: make a method to create a TMProposeSet message.
def test_encode_message():
    """Tests a basic encoded message."""
    message = TMProposeSet()
    message.proposeSeq = 0
    message.currentTxHash = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    message.nodePubKey = b"\x03\xec\xa5=\xb6\xd3\x18\xbc\xe3\xd5\x19\x9e\t\x86\xe4\xf7O\xa8\x85N'\xb5\r\xd8*c\x8f\x19\x90\xaa\xa7y\xb3"
    message.closeTime = 771346823
    message.signature = b'0D\x02 \r\x12\xfb6\x87\xba \xa9\xdb"\t2\xb9Wr\x9a\x9ek\xa66L\x0cr?u\n\x85]/\xf4\xaek\x02 R\x0e\xdf\x81C\x9a\xb3\xcc\xa1\xb0\xeaSH\xbc\xb0\xb9\x8e\x04+\x12\xabjS\xcf\xd3\xce\x86\xc6k-9\x93'
    message.previousledger = b"\x94\xcd\xd6\xce\xdd8!\xb4\xb0\x120\xbbR\xb5\xe5\x9f\xd8\xcf\x93HU\xecz\xd8\x98\x15\x12 \x84#\xb1\x97"

    encoded_message = PacketEncoderDecoder.encode_message(message, 33)

    final_message = b"\x00\x00\x00\xb7\x00!\x08\x00\x12 \x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x1a!\x03\xec\xa5=\xb6\xd3\x18\xbc\xe3\xd5\x19\x9e\t\x86\xe4\xf7O\xa8\x85N'\xb5\r\xd8*c\x8f\x19\x90\xaa\xa7y\xb3 \x87\xa3\xe7\xef\x02*F0D\x02 \r\x12\xfb6\x87\xba \xa9\xdb\"\t2\xb9Wr\x9a\x9ek\xa66L\x0cr?u\n\x85]/\xf4\xaek\x02 R\x0e\xdf\x81C\x9a\xb3\xcc\xa1\xb0\xeaSH\xbc\xb0\xb9\x8e\x04+\x12\xabjS\xcf\xd3\xce\x86\xc6k-9\x932 \x94\xcd\xd6\xce\xdd8!\xb4\xb0\x120\xbbR\xb5\xe5\x9f\xd8\xcf\x93HU\xecz\xd8\x98\x15\x12 \x84#\xb1\x97"

    assert encoded_message == final_message


def test_encode_empty_message():
    """Tests an encoding of an empty message will give error."""
    message = TMProposeSet()
    with pytest.raises(EncodeError) as excinfo:
        PacketEncoderDecoder.encode_message(message, 33)

    assert "Message protocol.TMProposeSet is missing required fields" in str(
        excinfo.value
    )


def test_encode_negative_message():
    """Tests an encoding of a negative message."""
    message = TMProposeSet()
    message.proposeSeq = 0
    message.currentTxHash = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    message.nodePubKey = b"\x03\xec\xa5=\xb6\xd3\x18\xbc\xe3\xd5\x19\x9e\t\x86\xe4\xf7O\xa8\x85N'\xb5\r\xd8*c\x8f\x19\x90\xaa\xa7y\xb3"
    message.closeTime = 771346823
    message.signature = b'0D\x02 \r\x12\xfb6\x87\xba \xa9\xdb"\t2\xb9Wr\x9a\x9ek\xa66L\x0cr?u\n\x85]/\xf4\xaek\x02 R\x0e\xdf\x81C\x9a\xb3\xcc\xa1\xb0\xeaSH\xbc\xb0\xb9\x8e\x04+\x12\xabjS\xcf\xd3\xce\x86\xc6k-9\x93'
    message.previousledger = b"\x94\xcd\xd6\xce\xdd8!\xb4\xb0\x120\xbbR\xb5\xe5\x9f\xd8\xcf\x93HU\xecz\xd8\x98\x15\x12 \x84#\xb1\x97"

    with pytest.raises(OverflowError) as excinfo:
        PacketEncoderDecoder.encode_message(message, -1)

    assert "can't convert negative int to unsigned" in str(excinfo.value)


def test_one_field_missing_encode_message():
    """Tests an encoding of a message while missing a field."""
    message = TMProposeSet()
    message.proposeSeq = 0
    message.currentTxHash = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    message.nodePubKey = b"\x03\xec\xa5=\xb6\xd3\x18\xbc\xe3\xd5\x19\x9e\t\x86\xe4\xf7O\xa8\x85N'\xb5\r\xd8*c\x8f\x19\x90\xaa\xa7y\xb3"
    message.closeTime = 771346823
    message.signature = b'0D\x02 \r\x12\xfb6\x87\xba \xa9\xdb"\t2\xb9Wr\x9a\x9ek\xa66L\x0cr?u\n\x85]/\xf4\xaek\x02 R\x0e\xdf\x81C\x9a\xb3\xcc\xa1\xb0\xeaSH\xbc\xb0\xb9\x8e\x04+\x12\xabjS\xcf\xd3\xce\x86\xc6k-9\x93'

    # Check the length of the encoded message

    with pytest.raises(EncodeError) as excinfo:
        PacketEncoderDecoder.encode_message(message, 33)

    assert "Message protocol.TMProposeSet is missing required fields" in str(
        excinfo.value
    )


def test_decode_packet():
    """Tests a decoding of a basic packet."""
    # Create a sample packet
    message = TMProposeSet()
    message.proposeSeq = 0
    message.currentTxHash = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    message.nodePubKey = b"\x03\xec\xa5=\xb6\xd3\x18\xbc\xe3\xd5\x19\x9e\t\x86\xe4\xf7O\xa8\x85N'\xb5\r\xd8*c\x8f\x19\x90\xaa\xa7y\xb3"
    message.closeTime = 771346823
    message.signature = b'0D\x02 \r\x12\xfb6\x87\xba \xa9\xdb"\t2\xb9Wr\x9a\x9ek\xa66L\x0cr?u\n\x85]/\xf4\xaek\x02 R\x0e\xdf\x81C\x9a\xb3\xcc\xa1\xb0\xeaSH\xbc\xb0\xb9\x8e\x04+\x12\xabjS\xcf\xd3\xce\x86\xc6k-9\x93'
    message.previousledger = b"\x94\xcd\xd6\xce\xdd8!\xb4\xb0\x120\xbbR\xb5\xe5\x9f\xd8\xcf\x93HU\xecz\xd8\x98\x15\x12 \x84#\xb1\x97"

    check = PacketEncoderDecoder.encode_message(message, 33)

    encoded_packet = packet_pb2.Packet(data=check, from_port=60000, to_port=60001)

    message_check, message_no = PacketEncoderDecoder.decode_packet(encoded_packet)

    message_type = 33
    assert message_type == message_no
    assert message_check == message


def test_decode_unknown_packet():
    """Tests a decoding of a packet that is an unknown type."""
    message_type = 99
    encoded_packet = packet_pb2.Packet(
        data=b"\x00\x00\x00\x0b"
        + message_type.to_bytes(2, "big")
        + b"\x08\x01\x12\x06\x08\x02\x10\x00"
    )

    with pytest.raises(DecodingNotSupportedError) as excinfo:
        PacketEncoderDecoder.decode_packet(encoded_packet)
    assert "Decoding of message type 99 not supported" in str(excinfo.value)


def test_decode_different_message_type():
    """Tests decoding a message that is not a propose."""
    # Create a sample packet with a different message type (TMTransaction)
    message = ripple_pb2.TMTransaction()
    message.rawTransaction = b"\x01" * 32
    message.status = 1

    message_type = 30

    serialized_message = message.SerializeToString()
    header = (len(serialized_message).to_bytes(4, "big")) + message_type.to_bytes(
        2, "big"
    )
    encoded_packet = packet_pb2.Packet(
        data=header + serialized_message, from_port=60001, to_port=60002
    )

    # Perform decoding
    decoded_message, decoded_message_type = PacketEncoderDecoder.decode_packet(
        encoded_packet
    )

    # Assertions
    assert isinstance(decoded_message, ripple_pb2.TMTransaction)
    assert decoded_message_type == message_type
    assert decoded_message == message


def test_signature_correct_with_propose():
    """Tests signature is correct with a propose message."""
    message = TMProposeSet()
    message.proposeSeq = 0
    message.currentTxHash = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    message.nodePubKey = b"\x03\xec\xa5=\xb6\xd3\x18\xbc\xe3\xd5\x19\x9e\t\x86\xe4\xf7O\xa8\x85N'\xb5\r\xd8*c\x8f\x19\x90\xaa\xa7y\xb3"
    message.closeTime = 771346823
    message.signature = b'0D\x02 \r\x12\xfb6\x87\xba \xa9\xdb"\t2\xb9Wr\x9a\x9ek\xa66L\x0cr?u\n\x85]/\xf4\xaek\x02 R\x0e\xdf\x81C\x9a\xb3\xcc\xa1\xb0\xeaSH\xbc\xb0\xb9\x8e\x04+\x12\xabjS\xcf\xd3\xce\x86\xc6k-9\x93'
    message.previousledger = b"\x94\xcd\xd6\xce\xdd8!\xb4\xb0\x120\xbbR\xb5\xe5\x9f\xd8\xcf\x93HU\xecz\xd8\x98\x15\x12 \x84#\xb1\x97"

    private_key = "pauPK4Fv9bYGGmbrhgzDTMZqENpe63bdWvnWfm3gbXovnvSfvdJ"

    original = message.signature

    priv_key = base58.b58decode(private_key, alphabet=base58.RIPPLE_ALPHABET)
    bs58_key = priv_key[1:33]

    PacketEncoderDecoder.sign_message(message, bs58_key.hex())

    assert message.signature != original
    assert (
        message.signature.hex()
        == "3045022100ce81f7d0bd5195ff27f7ec736beaa5cbd2e47bfd50b9fdda26036f4569ff0c67022003e6bf75081eb0cbf63adfa07b77218fa3c14a6904819a505a91da5c23bc02ab"
    )


def test_signature_error():
    """Tests a signature error for a message that is not a propose."""
    message = ripple_pb2.TMTransaction()
    message.rawTransaction = b"\x01" * 32
    message.status = 1

    message_type = 30

    serialized_message = message.SerializeToString()
    header = (len(serialized_message).to_bytes(4, "big")) + message_type.to_bytes(
        2, "big"
    )
    packet_pb2.Packet(data=header + serialized_message, from_port=60001, to_port=60002)

    private_key = "pauPK4Fv9bYGGmbrhgzDTMZqENpe63bdWvnWfm3gbXovnvSfvdJ"

    priv_key = base58.b58decode(private_key, alphabet=base58.RIPPLE_ALPHABET)
    bs58_key = priv_key[1:33]

    with pytest.raises(NotImplementedError) as excinfo:
        PacketEncoderDecoder.sign_message(message, bs58_key.hex())
    assert (
        "No signing method implemented for <class 'protos.ripple_pb2.TMTransaction'>"
        in str(excinfo.value)
    )
