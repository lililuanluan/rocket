"""Entry point of the application, run with python -m xrpl_controller."""

from pathlib import Path
from xrpl_controller.strategies import Strategy, RandomFuzzer
from .packet_server import serve

if __name__ == "__main__":
    Path("./execution_logs").mkdir(parents=True, exist_ok=True)
    strategy: Strategy = RandomFuzzer(0.01, 0.04, 1, 150)
    serve(strategy)
