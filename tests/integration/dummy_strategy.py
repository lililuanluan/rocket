"""This is a dummy strategy that does nothing. It is used for testing purposes."""

from xrpl_controller.iteration_type import NoneIteration
from xrpl_controller.strategies.strategy import Strategy


class DummyStrategy(Strategy):
    """Dummy strategy to be used for tests that allows to disable the available automatic processes in strategy."""

    def __init__(self):
        """Initialize the dummy strategy."""
        super().__init__(
            auto_partition=False,
            auto_parse_identical=False,
            auto_parse_subsets=False,
            keep_action_log=False,
            iteration_type=NoneIteration(timeout_seconds=20),
        )

    def handle_packet(self, packet):
        """Return the packet as is."""
        return packet.data, 0
