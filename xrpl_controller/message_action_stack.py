"""Class which stores last received MessageAction entries."""

from xrpl_controller.message_action import MessageAction


class MessageActionStack:
    """MessageAction list which holds the last `capacity` amount of given entries."""

    def __init__(self, capacity):
        """Initialize fields."""
        if capacity < 1:
            raise ValueError("Capacity must be greater than 0")

        self.capacity = capacity
        self.messages = []

    def add(self, message: MessageAction):
        """Add a new MessageAction entry."""
        while len(self.messages) >= self.capacity:
            self.messages.pop(0)

        self.messages.append(message)

    def check_previous_messages(self, message: bytes) -> tuple[bool, tuple[bytes, int]]:
        """
        Parse a message automatically to a final state with an action if it was matching to the one of the previous `capacity` amount of messages.

        Args:
            message: The message to be checked for parsing

        Returns:
            Tuple(bool, Tuple(bytes, int)): Boolean indicating success along with final message and action.
        """
        for message_action in self.messages:
            if message == message_action.initial_message:
                return True, (message_action.final_message, message_action.action)

        return False, (b"", -1)
