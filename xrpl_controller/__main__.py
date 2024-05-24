"""Entry point of the application, run with python -m xrpl_controller."""

from pathlib import Path
from xrpl_controller.random_fuzzer import RandomFuzzer
from xrpl_controller.strategy import Strategy
from .core import print_hi
from .packet_server import serve

if __name__ == "__main__":
    Path("../execution_logs").mkdir(parents=True, exist_ok=True)
    strategy: Strategy = RandomFuzzer(0.01, 0.95, 0.04, 1, 150)
    serve(strategy)
