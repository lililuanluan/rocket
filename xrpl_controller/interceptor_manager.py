"""Contains functionality to easily interact with the network packet interceptor subprocess."""

from subprocess import PIPE, Popen
from threading import Thread

from loguru import logger


class InterceptorManager:
    """Class for interacting with the network packet interceptor subprocess."""

    def __init__(self):
        """Initialize the InterceptorManager, with None for the process variable."""
        self.process = None

    @staticmethod
    def __check_output(proc: Popen):
        stdout, stderr = proc.communicate()
        if stdout:
            logger.info(stdout)
        if stderr:
            logger.info(stderr)

    def start_new(self):
        """Starts the xrpl-packet-interceptor subprocess, and spawns a thread checking for output."""
        logger.info("Starting interceptor")
        self.process = Popen(
            ["./xrpl-packet-interceptor"],
            cwd="./interceptor",
            stdin=PIPE,
            stdout=PIPE,
            stderr=PIPE,
            text=True,
        )
        t = Thread(target=self.__check_output, args=[self.process])
        t.start()

    def restart(self):
        """Stops and starts the xrpl-packet-interceptor subprocess."""
        logger.info("Stopping interceptor")
        if self.process:
            self.process.terminate()
        self.start_new()
