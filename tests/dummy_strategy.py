"""This is a dummy strategy that does nothing. It is used for testing purposes."""

from xrpl_controller.strategies.strategy import Strategy


class DummyStrategy(Strategy):
    """Dummy strategy to be used for tests that allows to disable the available automatic processes in strategy."""

    def __init__(self, auto_partition, auto_parse_identical, keep_action_log):
        """Initialize the dummy strategy."""
        super().__init__(
            auto_partition=auto_partition,
            auto_parse_identical=auto_parse_identical,
            keep_action_log=keep_action_log,
        )

    def handle_packet(self, packet):
        """Return the packet as is."""
        return packet.data, 0
