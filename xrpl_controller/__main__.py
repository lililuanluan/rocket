"""Entry point of the application, run with python -m xrpl_controller."""

from .core import print_hi
from .packet_server import serve

if __name__ == "__main__":
    print_hi("PyCharm")
    serve()
