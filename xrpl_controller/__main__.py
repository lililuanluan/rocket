"""Entry point of the application, run with python -m xrpl_controller."""

# from xrpl_controller.strategies.PacketHandler import PacketHandler

from xrpl_controller.strategies import RandomFuzzer, Strategy

from .packet_server import serve

if __name__ == "__main__":
    strategy: Strategy = RandomFuzzer(0.01, 0.04, 1, 150)
    serve(strategy)
    print("Controller Module started.")
