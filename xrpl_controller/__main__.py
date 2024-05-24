"""Entry point of the application, run with python -m xrpl_controller."""

from xrpl_controller.strategies import Strategy, RandomFuzzer
from xrpl_controller.strategies.PacketHandler import PacketHandler

from .packet_server import serve

if __name__ == "__main__":
    strategy: Strategy = PacketHandler(0.01, 0.04, 1, 150)
    serve(strategy)
