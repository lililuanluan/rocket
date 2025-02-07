"""File which stores interchangeably used variables."""

from protos import ripple_pb2
from rocket_controller.validator_node_info import (
    SocketAddress,
    ValidatorKeyData,
    ValidatorNode,
)

node_0 = ValidatorNode(
    SocketAddress("test_peer", 10),
    SocketAddress("test-ws-pub", 20),
    SocketAddress("test-ws-adm", 30),
    SocketAddress("test-rpc", 40),
    ValidatorKeyData("status0", "keyZER", "K3YZER", "PUBZER", "T3STZER"),
)

node_1 = ValidatorNode(
    SocketAddress("test_peer", 11),
    SocketAddress("test-ws-pub", 21),
    SocketAddress("test-ws-adm", 31),
    SocketAddress("test-rpc", 41),
    ValidatorKeyData("status1", "keyNE", "K3YNE", "PUBNE", "T3STNE"),
)

node_2 = ValidatorNode(
    SocketAddress("test_peer", 12),
    SocketAddress("test-ws-pub", 22),
    SocketAddress("test-ws-adm", 32),
    SocketAddress("test-rpc", 42),
    ValidatorKeyData("status2", "keyTW", "K3YTW", "PUBTW", "T3STTW"),
)

node_3 = ValidatorNode(
    SocketAddress("test_peer", 13),
    SocketAddress("test-ws-pub", 23),
    SocketAddress("test-ws-adm", 33),
    SocketAddress("test-rpc", 43),
    ValidatorKeyData("status3", "keyTHREE", "K3YTHREE", "PUBTHREE", "T3STTHREE"),
)

configs = (
    {
        "base_port_peer": 60000,
        "base_port_ws": 61000,
        "base_port_ws_admin": 62000,
        "base_port_rpc": 63000,
        "number_of_nodes": 3,
        "network_partition": [[0, 1, 2]],
    },
    {
        "delay_probability": 0.6,
        "drop_probability": 0,
        "min_delay_ms": 10,
        "max_delay_ms": 150,
        "seed": 10,
    },
)

status_msg_1 = ripple_pb2.TMStatusChange(
    newStatus=2,
    newEvent=1,
    ledgerSeq=2,
    ledgerHash=b"abcdef",
    ledgerHashPrevious=b"123456",
    networkTime=1000,
    firstSeq=0,
    lastSeq=2,
)

status_msg_2 = ripple_pb2.TMStatusChange(
    newStatus=2,
    newEvent=1,
    ledgerSeq=2,
    ledgerHash=b"abcdefg",
    ledgerHashPrevious=b"1234567",
    networkTime=1000,
    firstSeq=0,
    lastSeq=3,
)
