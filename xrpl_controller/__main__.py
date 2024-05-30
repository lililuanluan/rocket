"""Entry point of the application, run with python -m xrpl_controller."""

from xrpl_controller.strategies import Strategy, RandomFuzzer
from xrpl_controller.strategies.PacketHandler import PacketHandler
from xrpl_controller.strategies.SpecificPacketHandler import SpecificPacketHandler

from .packet_server import serve

if __name__ == "__main__":
    strategy: Strategy = SpecificPacketHandler(0.01, 0.04, 1, 150, None, None)
    serve(strategy)
