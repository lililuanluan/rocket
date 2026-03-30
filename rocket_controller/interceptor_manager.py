"""This module contains functionality to easily interact with the network packet interceptor subprocess."""

import traceback
from subprocess import PIPE, Popen, TimeoutExpired
from sys import platform
from threading import Thread
import sys
import os
from pathlib import Path

import docker
from docker import DockerClient
from loguru import logger


class InterceptorManager:
    """Class for interacting with the network packet interceptor subprocess."""

    def __init__(self, grpc_port: int = 50051, cluster_id: str = "", rippled_img: str | None = None):
        """Initialize the InterceptorManager, with None for the process variable."""
        self.process: Popen | None = None
        self.grpc_port = grpc_port
        # store the cluster identifier; this will be written into the
        # ROCKET_ environment variable when launching the
        # interceptor so CLUSTER_ID is available for the Rust side.
        self.cluster_id = cluster_id
        self.rippled_img = rippled_img if rippled_img is not None else "xrpllabsofficial/xrpld:2.3.0" # use the same default as in the interceptor
        logger.info(f"Using rippled image: {self.rippled_img}")

    @staticmethod
    def _get_volumes_root() -> str:
        """Return the root directory used for validator runtime data.

        Prefer an explicit env var. Otherwise, keep runtime data under the
        configured temporary directory so local/server runs do not fill Docker's
        default storage root under ``/var/lib/docker``.
        """
        configured = os.environ.get("ROCKET_VOLUMES_ROOT")
        if configured:
            return str(Path(configured).resolve())

        tmp_root = os.environ.get("ROCKET_TMPDIR") or os.environ.get("TMPDIR")
        if tmp_root:
            return str((Path(tmp_root).resolve() / "volumes"))

        return "/tmp/rocket-tmp/volumes"

    @staticmethod
    def _get_network_root() -> str:
        """Return the root directory used for generated interceptor configs."""
        configured = os.environ.get("ROCKET_NETWORK_ROOT")
        if configured:
            return str(Path(configured).resolve())

        tmp_root = os.environ.get("ROCKET_TMPDIR") or os.environ.get("TMPDIR")
        if tmp_root:
            return str((Path(tmp_root).resolve() / "network"))

        return "/tmp/rocket-tmp/network"

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
    def cleanup_docker_containers(container_names: list[str]):
        """Stop the validator containers."""
        docker_client: DockerClient = docker.from_env()
        for name in container_names:
            try:
                container = docker_client.containers.get(name)
                container.stop()
                container.remove(force=True)
            except Exception as e:
                pass

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
        process_env["ROCKET_CLUSTER_ID"] = self.cluster_id
        process_env["RIPPLE_IMAGE"] = self.rippled_img
        process_env["ROCKET_VOLUMES_ROOT"] = self._get_volumes_root()
        process_env["ROCKET_NETWORK_ROOT"] = self._get_network_root()
        process_env.setdefault("ROCKET_HOST_UID", str(os.getuid()))
        process_env.setdefault("ROCKET_HOST_GID", str(os.getgid()))
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
