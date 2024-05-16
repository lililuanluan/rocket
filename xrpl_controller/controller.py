# The packet received here are the raw bytes from the sslstream, which can be decoded with the ripple protobuffer.
def handle_packet(packet):
    print(f"Packet received: {packet}")