"""Entry point of the application, run with python -m xrpl_controller."""

from xrpl_controller.strategies import Strategy
from xrpl_controller.strategies.handling import Handling

from .packet_server import serve

if __name__ == "__main__":
    strategy: Strategy = Handling(0.01, 0.04, 1, 150)
    serve(strategy)
    print("Controller Module started.")
