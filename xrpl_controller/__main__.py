"""Entry point of the application, run with python -m xrpl_controller."""

from xrpl_controller.random_fuzzer import RandomFuzzer
from xrpl_controller.strategy import Strategy
from .core import print_hi
from .packet_server import serve

if __name__ == "__main__":
    print_hi("PyCharm")
    strategy: Strategy = RandomFuzzer()
    serve(strategy)
