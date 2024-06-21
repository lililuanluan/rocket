"""Tests for Strategy class."""

from encodings.utf_8 import encode
from unittest.mock import MagicMock, Mock, patch

from protos import packet_pb2
from tests.variable_store import configs, node_0, node_1, node_2, status_msg
from xrpl_controller.core import MAX_U32
from xrpl_controller.iteration_type import LedgerBasedIteration
from xrpl_controller.strategies import RandomFuzzer
from xrpl_controller.strategies.encoder_decoder import PacketEncoderDecoder


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_init(mock_init_configs):
    """Test whether Strategy attributes get initialized correctly."""
    strategy = RandomFuzzer(iteration_type=Mock())
    mock_init_configs.assert_called_once()
    assert strategy.network.communication_matrix == []
    assert strategy.auto_partition
    assert strategy.auto_parse_identical
    assert strategy.network.prev_message_action_matrix == []
    assert strategy.keep_action_log


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_update_network(mock_init_configs):
    """Test whether Strategy attributes get updated correctly with update_network function."""
    strategy = RandomFuzzer(iteration_type=Mock())
    mock_init_configs.assert_called_once()

    strategy.update_network([node_0, node_1, node_2])
    assert strategy.network.validator_node_list == [node_0, node_1, node_2]
    assert strategy.network.node_amount == 3
    assert strategy.network.port_to_id_dict == {10: 0, 11: 1, 12: 2}
    assert strategy.network.id_to_port_dict == {0: 10, 1: 11, 2: 12}
    assert strategy.network.id_to_port(2) == 12
    assert strategy.network.port_to_id(12) == 2
    assert strategy.network.communication_matrix == [
        [False, True, True],
        [True, False, True],
        [True, True, False],
    ]

    assert strategy.network.subsets_dict == {0: [], 1: [], 2: []}

    assert len(strategy.network.prev_message_action_matrix) == 3
    for row in strategy.network.prev_message_action_matrix:
        assert len(row) == 3
        for item in row:
            assert item.initial_message == b""
            assert item.final_message == b""
            assert item.action == -1


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_process_message(mock_init_configs):
    """Test for process_message function."""
    strategy = RandomFuzzer(iteration_type=Mock())
    mock_init_configs.assert_called_once()

    strategy.update_network([node_0, node_1, node_2])
    packet_ack = packet_pb2.Packet(data=b"testtest", from_port=10, to_port=11)
    assert strategy.process_packet(packet_ack) == (b"testtest", 119)

    # Check whether action differs from previous one, could be flaky, but we used a seed
    packet_ack = packet_pb2.Packet(data=b"testtest2", from_port=10, to_port=11)
    assert strategy.process_packet(packet_ack) == (b"testtest2", 13)

    # Check whether set_message gets modified
    assert (
        strategy.network.prev_message_action_matrix[0][1].initial_message
        == b"testtest2"
    )
    assert strategy.network.prev_message_action_matrix[0][1].action == 13
    assert (
        strategy.network.prev_message_action_matrix[0][1].final_message == b"testtest2"
    )

    # Check whether messages get dropped automatically through auto partition
    strategy.network.partition_network([[0, 1], [2]])
    for i in range(100):
        msg = encode("testtest" + str(i))[0]  # Just arbitrary encoding
        packet_ack = packet_pb2.Packet(data=msg, from_port=10, to_port=12)
        assert strategy.process_packet(packet_ack) == (msg, MAX_U32)

    # Check whether result will always stay the same with auto parse identical messages
    packet_ack = packet_pb2.Packet(data=b"testtest", from_port=10, to_port=12)
    result = strategy.process_packet(packet_ack)
    for _ in range(100):
        packet_ack = packet_pb2.Packet(data=b"testtest", from_port=10, to_port=12)
        assert strategy.process_packet(packet_ack) == result


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_update_status(mock_init_configs):
    """Test whether a statuschange message correctly updates the iteration."""
    message = PacketEncoderDecoder.encode_message(status_msg, message_type=34)
    packet = packet_pb2.Packet(data=message, from_port=10, to_port=11)

    iteration_type = LedgerBasedIteration(
        max_ledger_seq=5, max_iterations=10, interceptor_manager=Mock()
    )
    iteration_type.start_timeout_timer = MagicMock()
    iteration_type.update_iteration = MagicMock()
    iteration_type.set_server = MagicMock()

    strategy = RandomFuzzer(iteration_type=iteration_type)
    mock_init_configs.assert_called_once()

    strategy.update_status(packet)
    iteration_type.update_iteration.assert_called_once()


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_update_status_exception(mock_init_configs):
    """Test whether an invalid message type gets ignored."""
    message = PacketEncoderDecoder.encode_message(status_msg, message_type=99)
    packet = packet_pb2.Packet(data=message, from_port=10, to_port=11)

    iteration_type = LedgerBasedIteration(
        max_ledger_seq=5, max_iterations=10, interceptor_manager=Mock()
    )
    iteration_type.start_timeout_timer = MagicMock()
    iteration_type.update_iteration = MagicMock()
    iteration_type.set_server = MagicMock()

    strategy = RandomFuzzer(iteration_type=iteration_type)
    mock_init_configs.assert_called_once()

    strategy.update_status(packet)
    iteration_type.update_iteration.assert_not_called()


@patch(
    "xrpl_controller.strategies.random_fuzzer.Strategy.init_configs",
    return_value=configs,
)
def test_update_status_other_message(mock_init_configs):
    """Test whether a message type different from TMStatusChange 34 is ignored."""
    message = PacketEncoderDecoder.encode_message(status_msg, message_type=15)
    packet = packet_pb2.Packet(data=message, from_port=10, to_port=11)

    iteration_type = LedgerBasedIteration(
        max_ledger_seq=5, max_iterations=10, interceptor_manager=Mock()
    )
    iteration_type.start_timeout_timer = MagicMock()
    iteration_type.update_iteration = MagicMock()
    iteration_type.set_server = MagicMock()

    strategy = RandomFuzzer(iteration_type=iteration_type)
    mock_init_configs.assert_called_once()

    strategy.update_status(packet)
    iteration_type.update_iteration.assert_not_called()
