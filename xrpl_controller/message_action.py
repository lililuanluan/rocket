"""Class which stores information on taken actions on intercepted messages."""


class MessageAction:
    """Object which holds information used to perform same actions on identical messages."""

    def __init__(
        self, initial_message: bytes = b"", final_message: bytes = b"", action: int = -1
    ):
        """
        Instantiate fields, these initial values should never be used, rather, they should be modified.

        Args:
            initial_message (bytes, optional): The initial pre-processed message. Defaults to empty bytes.
            final_message (bytes, optional): The final processed message. Defaults to empty bytes.
            action (int, optional): The taken action. Defaults to -1.
        """
        self.initial_message = initial_message
        self.final_message = final_message
        self.action = action

    def set_initial_message(self, initial_message: bytes) -> "MessageAction":
        """
        Set the initial_message field.

        Args:
            initial_message: The initial pre-processed message.

        Returns:
            MessageAction: The MessageAction this method was called on.
        """
        self.initial_message = initial_message
        return self

    def set_final_message(self, final_message: bytes) -> "MessageAction":
        """
        Set the final_message field.

        Args:
            final_message: The final processed message.

        Returns:
            MessageAction: The MessageAction this method was called on.
        """
        self.final_message = final_message
        return self

    def set_action(self, action: int) -> "MessageAction":
        """
        Set the action field.

        Args:
            action: The taken action.

        Returns:
            MessageAction: The MessageAction this method was called on.
        """
        self.action = action
        return self
