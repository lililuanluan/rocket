"""This module contains functionality to easily interact with the network packet interceptor subprocess."""

import traceback
from subprocess import PIPE, Popen, TimeoutExpired
from sys import platform
from threading import Thread
import sys
import os

import docker
from docker import DockerClient
from loguru import logger


class InterceptorManager:
    """Class for interacting with the network packet interceptor subprocess."""

    def __init__(self, grpc_port: int = 50051):
        """Initialize the InterceptorManager, with None for the process variable."""
        self.process: Popen | None = None
        self.grpc_port = grpc_port

    @staticmethod
    def __stream_reader(pipe, stream):
        """Read a process stream line-by-line and log it immediately."""
        if stream is None:
            return
        try:
            for line in iter(stream.readline, ""):
                if not line:
                    break
                # 如果是stdout，则输出黄色，如果是stderr，输出蓝色
                try:
                    if pipe == sys.stdout:
                        pipe.write(f"\x1b[33m{line}\x1b[0m")
                    else:
                        pipe.write(f"\x1b[34m{line}\x1b[0m")
                except TypeError:
                    # Some pipes expect bytes (unlikely here), fall back to encode
                    if pipe == sys.stdout:
                        pipe.write(f"\x1b[33m{line}\x1b[0m".encode())
                    else:
                        pipe.write(f"\x1b[34m{line}\x1b[0m".encode())
                pipe.flush()
               
        except Exception:
            logger.exception("Failed to read interceptor stream")

    @staticmethod
    def __check_output(proc: Popen):
        """Log the stdout and stderr of the subprocess in real time."""
        # Spawn two daemon threads to stream stdout and stderr line-by-line.
        Thread(
            target=InterceptorManager.__stream_reader,
            args=(sys.stdout, proc.stdout),
            daemon=True,
        ).start()
        Thread(
            target=InterceptorManager.__stream_reader,
            args=(sys.stderr, proc.stderr),
            daemon=True,
        ).start()
        # Wait for process to exit so this thread doesn't return immediately.
        try:
            proc.wait()
        except Exception:
            logger.exception("Error while waiting for interceptor process")

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
        process_env = os.environ.copy()
        process_env["ROCKET_GRPC_PORT"] = str(self.grpc_port)
        try:
            self.process = Popen(
                [f"./{file}"],
                cwd="./rocket_interceptor",
                stdin=PIPE,
                stdout=PIPE,
                stderr=PIPE,
                text=True,
                env=process_env,
            )
        except FileNotFoundError as exc:
            logger.error(
                "Could not find the rocket-interceptor executable. Did you build the interceptor?"
            )
            traceback.print_exception(exc)
            exit(2)

        t = Thread(target=self.__check_output, args=[self.process])
        t.start()

    def restart(self):
        """Stops and starts the rocket-interceptor subprocess."""
        self.stop()
        self.start_new()

    def stop(self):
        """Stops the rocket-interceptor subprocess."""
        # Check if this is the end of an active run
        if self.process:
            logger.info("Stopping interceptor")
            self.process.terminate()
            try:
                self.process.wait(timeout=5.0)
            except TimeoutExpired:
                self.process.kill()
