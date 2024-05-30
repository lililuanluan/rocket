"""Class which stores information on taken actions on intercepted messages."""


class MessageAction:
    """Object which holds information used to filter identical messages."""
    def __init__(self):
        """Instantiate fields, these initial values should never be used, rather, they should be modified."""
        self.initial_message: bytes = bytes()
        self.final_message: bytes = bytes()
        self.action = -1
