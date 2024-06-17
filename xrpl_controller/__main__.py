"""Entry point of the application, run with python -m xrpl_controller."""

from xrpl_controller.strategies import Strategy
from xrpl_controller.strategies.random_fuzzer import RandomFuzzer

from xrpl_controller.packet_server import serve

if __name__ == "__main__":
    strategy: Strategy = RandomFuzzer()
    serve(strategy)
