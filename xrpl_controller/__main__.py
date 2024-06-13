"""Entry point of the application, run with python -m xrpl_controller."""

from xrpl_controller.strategies import Strategy
from xrpl_controller.strategies.mutation_example import MutationExample

from .packet_server import serve

if __name__ == "__main__":
    strategy: Strategy = MutationExample()
    serve(strategy)
