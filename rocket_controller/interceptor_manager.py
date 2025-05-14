"""This module contains functionality to easily interact with the network packet interceptor subprocess."""

import traceback
from subprocess import PIPE, Popen, TimeoutExpired
from sys import platform
from threading import Thread

import docker
from docker import DockerClient
from loguru import logger


class InterceptorManager:
    """Class for interacting with the network packet interceptor subprocess."""

    def __init__(self):
        """Initialize the InterceptorManager, with None for the process variable."""
        self.process: Popen | None = None
        self.running = False
        self.output_thread: Thread | None = None

    @staticmethod
    def __check_output(proc: Popen, running_flag):
        """Continuously log the stdout and stderr of the subprocess."""
        try:
            while running_flag() and proc.poll() is None:
                output = proc.stdout.readline()
                if output:
                    logger.debug(f"[Interceptor stdout] {output.strip()}")
                error = proc.stderr.readline()
                if error:
                    logger.error(f"[Interceptor stderr] {error.strip()}")
        except Exception as e:
            logger.error(f"Error while reading subprocess output: {e}")

    @staticmethod
    def cleanup_docker_containers():
        """Stop the validator containers."""
        docker_client: DockerClient = docker.from_env()
        for c in docker_client.containers.list():
            if "validator_" in c.name:
                c.stop()

    def start_new(self):
        """Starts the rocket-interceptor subprocess, and spawns a thread checking for output."""
        file = (
            "rocket-interceptor"
            if platform != "win32"
            else "/rocket_interceptor/rocket-interceptor.exe"
        )
        logger.info("Starting interceptor")
        try:
            self.process = Popen(
                [f"./{file}"],
                cwd="./rocket_interceptor",
                stdin=PIPE,
                stdout=PIPE,
                stderr=PIPE,
                text=True,
                bufsize=1
            )
            self.running = True
        except FileNotFoundError as exc:
            logger.error(
                "Could not find the rocket-interceptor executable. Did you build the interceptor?"
            )
            traceback.print_exception(exc)
            exit(2)

        self.output_thread = Thread(target=self.__check_output, args=[self.process, lambda: self.running], daemon=True)
        self.output_thread.start()

    def restart(self):
        """Stops and starts the rocket-interceptor subprocess."""
        self.stop()
        self.start_new()

    def stop(self):
        """Stops the rocket-interceptor subprocess."""
        if self.process:
            logger.info("Stopping interceptor")
            self.running = False
            self.process.terminate()
            try:
                self.process.wait(timeout=5.0)
            except TimeoutExpired:
                logger.warning(
                    "Interceptor process did not terminate in time, killing it."
                )
                self.process.kill()
            finally:
                if self.output_thread:
                    self.output_thread.join()
                    self.output_thread = None
                self.process = None
