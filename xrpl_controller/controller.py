"""This module is responsible for handling the incoming packets from the interceptor."""


def handle_packet(packet):
    """
    The packet received here are the raw bytes from the sslstream, which can be decoded with the ripple protobuffer.

    Args:
        packet: intercepted sslstream

    Returns: None

    """
    print(f"Packet received: {packet}")
