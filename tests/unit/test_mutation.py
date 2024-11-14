"""Tests for mutating a packet using handle method."""

from unittest.mock import Mock

import base58
from xrpl.core.keypairs.secp256k1 import SECP256K1

from protos import packet_pb2, ripple_pb2
from protos.packet_pb2 import Packet
from protos.ripple_pb2 import TMProposeSet
from xrpl_controller.encoder_decoder import PacketEncoderDecoder
from xrpl_controller.strategies import Strategy
from xrpl_controller.strategies.mutation_example import MutationExample


def test_mutation_propose():
    """Tests for a basic mutation of a propose message."""
    strategy: Strategy = MutationExample(iteration_type=Mock())
    # Create a sample packet
    message = TMProposeSet()
    message.proposeSeq = 0
    message.currentTxHash = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    message.nodePubKey = b"\x03\xec\xa5=\xb6\xd3\x18\xbc\xe3\xd5\x19\x9e\t\x86\xe4\xf7O\xa8\x85N'\xb5\r\xd8*c\x8f\x19\x90\xaa\xa7y\xb3"
    message.closeTime = 771346823
    message.signature = b'0D\x02 \r\x12\xfb6\x87\xba \xa9\xdb"\t2\xb9Wr\x9a\x9ek\xa66L\x0cr?u\n\x85]/\xf4\xaek\x02 R\x0e\xdf\x81C\x9a\xb3\xcc\xa1\xb0\xeaSH\xbc\xb0\xb9\x8e\x04+\x12\xabjS\xcf\xd3\xce\x86\xc6k-9\x93'
    message.previousledger = b"\x94\xcd\xd6\xce\xdd8!\xb4\xb0\x120\xbbR\xb5\xe5\x9f\xd8\xcf\x93HU\xecz\xd8\x98\x15\x12 \x84#\xb1\x97"

    private_key = "pauPK4Fv9bYGGmbrhgzDTMZqENpe63bdWvnWfm3gbXovnvSfvdJ"

    priv_key = base58.b58decode(private_key, alphabet=base58.RIPPLE_ALPHABET)
    bs58_key = priv_key[1:33]

    strategy.network.public_to_private_key_map = {
        message.nodePubKey.hex(): bs58_key.hex()
    }

    # Encode the message into a packet
    encoded_data = PacketEncoderDecoder.encode_message(message, 33)
    packet: Packet = packet_pb2.Packet(
        data=encoded_data, from_port=60000, to_port=60001
    )

    # Mutate the packet data
    mutated_data, action = strategy.handle_packet(packet)

    # Create a new packet with mutated data
    mutated_packet = packet_pb2.Packet(
        data=mutated_data, from_port=60000, to_port=60001
    )

    # Decode the mutated packet
    mutated_message, mutated_message_type = PacketEncoderDecoder.decode_packet(
        mutated_packet
    )

    # Validate the mutation effect
    assert mutated_message_type == 33
    assert mutated_message.closeTime != message.closeTime

    # Optionally, assert other aspects of the mutated message for thorough testing
    assert mutated_message.proposeSeq == message.proposeSeq
    assert mutated_message.currentTxHash == message.currentTxHash
    assert mutated_message.nodePubKey == message.nodePubKey
    assert mutated_message.signature != message.signature
    assert mutated_message.previousledger == message.previousledger


def test_no_mutation_not_propose():
    """Tests for no mutating occuring when it is not a propose message."""
    strategy: Strategy = MutationExample(iteration_type=Mock())
    # Create a sample packet
    message = ripple_pb2.TMTransaction()
    message.rawTransaction = b"\x01" * 32
    message.status = 1

    # Encode the message into a packet
    encoded_data = PacketEncoderDecoder.encode_message(message, 30)
    packet: Packet = packet_pb2.Packet(
        data=encoded_data, from_port=60001, to_port=60000
    )

    # Mutate the packet data
    mutated_data, action = strategy.handle_packet(packet)

    # Create a new packet with mutated data
    mutated_packet = packet_pb2.Packet(
        data=mutated_data, from_port=60000, to_port=60001
    )

    # Decode the mutated packet
    mutated_message, mutated_message_type = PacketEncoderDecoder.decode_packet(
        mutated_packet
    )

    # Validate the mutation effect

    assert mutated_message.rawTransaction == message.rawTransaction

    # Optionally, assert other aspects of the mutated message for thorough testing
    assert mutated_message.status == message.status


def test_mutation_decoding_not_support():
    """Tests a decoding of a packet that is an unknown type."""
    strategy: Strategy = MutationExample(iteration_type=Mock())
    message_type = 99
    encoded_packet = packet_pb2.Packet(
        data=b"\x00\x00\x00\x0b"
        + message_type.to_bytes(2, "big")
        + b"\x08\x01\x12\x06\x08\x02\x10\x00"
    )

    result_data, action = strategy.handle_packet(encoded_packet)

    assert result_data == encoded_packet.data
    assert action == 0


def test_mutation_propose_correct_signature_change():
    """Test for checking the signature is different from original after mutating a packet."""
    strategy: Strategy = MutationExample(iteration_type=Mock())
    message = TMProposeSet()
    message.proposeSeq = 0
    message.currentTxHash = b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    message.nodePubKey = b"\x03\x97i\xce\xce\x08\x95)\xad\x9c\xd4F?\xc7H\x01\x9f\xb6H\x7fU*1\xa7'PH\xbfZI\x9b\xf9\xf5"
    message.closeTime = 771411087
    message.signature = b"0D\x02 F\xfe\x89G\xa3\r\x7f\n)9\xb5\x81\x1aEts\xf8\xb2\xc4\r\xb4Ef\xdc\t\xed\xaf\x0c\xb5\x93p\x97\x02 \x04\xf9-G\x979!\xe8\x92\\\x07N7=_\x95\xf1\xf3\xf4\x87|sU\x08\xf2\x04\xf9\x90\x87\xbc\xe2\x88"
    message.previousledger = b"\x1d\xc32\xac\x97\x18\xf7\xe7\xf5cv\xbb\xc3[\xa6^\xddt\x05\x08\xbb\x8b\xefn3\x10\xce-\x1d\xc9\xd2\xa1"

    # for the first assert we are initially checking that the signature is
    # correct and the same if no mutation is applied (Mutation.handlepacket)
    # and then an assert that the message signatures are different becasue
    # the mutation has been applied
    org_sig: bytes = message.signature

    private_key = "pnQoFmvY9rq819fBSPiy9daGk6yYRWBrYZcY7GmxHwyrWZpKGjV"

    pub_key = base58.b58decode(
        "n9Mdv672BQY4dvLfmnqSSme4vW1obGu4a9eNL5PQNqDfTk3qyYHd",
        alphabet=base58.RIPPLE_ALPHABET,
    )
    assert pub_key[1:34] == message.nodePubKey

    msg = (
        b"\x50\x52\x50\x00"
        + message.proposeSeq.to_bytes(4, "big")
        + message.closeTime.to_bytes(4, "big")
        + message.previousledger
        + message.currentTxHash
    )

    priv_key = base58.b58decode(private_key, alphabet=base58.RIPPLE_ALPHABET)
    bs58_key = priv_key[1:33]

    final_sig = SECP256K1.sign(msg, bs58_key.hex())

    assert org_sig == final_sig

    strategy.network.public_to_private_key_map = {
        message.nodePubKey.hex(): bs58_key.hex()
    }

    # Here we are now checking the signature difference after we mutate the packet
    # Encode the message into a packet
    encoded_data = PacketEncoderDecoder.encode_message(message, 33)
    packet: Packet = packet_pb2.Packet(
        data=encoded_data, from_port=60000, to_port=60001
    )

    # Mutate the packet data
    mutated_data, action = strategy.handle_packet(packet)

    # Create a new packet with mutated data
    mutated_packet = packet_pb2.Packet(
        data=mutated_data, from_port=60000, to_port=60001
    )

    # Decode the mutated packet
    mutated_message, mutated_message_type = PacketEncoderDecoder.decode_packet(
        mutated_packet
    )

    # Validate the mutation effect
    assert mutated_message_type == 33
    assert mutated_message.closeTime != message.closeTime

    # Optionally, assert other aspects of the mutated message for thorough testing
    assert mutated_message.proposeSeq == message.proposeSeq
    assert mutated_message.currentTxHash == message.currentTxHash
    assert mutated_message.nodePubKey == message.nodePubKey
    assert mutated_message.signature != message.signature
    assert mutated_message.previousledger == message.previousledger
