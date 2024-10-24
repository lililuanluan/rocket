"""This module contains a class which stores received MessageAction entries."""

from xrpl_controller.message_action import MessageAction


class MessageActionBuffer:
    """MessageAction list which holds the last `capacity` amount of given entries."""

    def __init__(self, capacity: int):
        """
        Initialize a new MessageActionBuffer.

        Args:
            capacity (int): Maximum number of entries to store in buffer.

        Raises:
            ValueError: If given capacity is not greater than 0.
        """
        if capacity < 1:
            raise ValueError("Capacity must be greater than 0.")

        self.capacity = capacity
        self.messages: list[MessageAction] = []

    def add(self, message: MessageAction):
        """
        Add a new MessageAction entry.

        Args:
            message (MessageAction): MessageAction to add.
        """
        while len(self.messages) >= self.capacity:
            self.messages.pop(0)

        self.messages.append(message)

    def match_previous_messages(self, message: bytes) -> tuple[bool, tuple[bytes, int]]:
        """
        Parse a message automatically to a final state with an action if it was matching to the one of the previous `capacity` amount of messages.

        Args:
            message: The message to be checked for parsing

        Returns:
            Tuple(bool, Tuple(bytes, int)): Boolean indicating success along with final message and action.
            Returns original message and 0 as action when no match was found.
        """
        for message_action in self.messages:
            if message == message_action.initial_message:
                return True, (message_action.final_message, message_action.action)

        return False, (message, 0)
