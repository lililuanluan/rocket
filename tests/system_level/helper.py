"""Helper methods to aid in quickly implementing system-level tests."""

import os
import stat
import subprocess
from typing import Any

from git import Repo
from loguru import logger
from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.models import ServerInfo


async def fetch_node_info(ws_port: int) -> Any | None:
    """
    Fetch the node info from the websocket server at a specific port.

    Args:
        ws_port: the websocket server port to retrieve the node info from.

    Returns:
        A dictionary containing the node info if available, None otherwise.
    """
    async with AsyncWebsocketClient(f"ws://localhost:{ws_port}") as client:
        info = ServerInfo()
        ledger_response = await client.request(info)
        if not ledger_response.is_successful():
            logger.error("request failed")
            return None
        await client.close()
        return ledger_response.result.get("info")


def start_interceptor() -> None:
    """
    Starts the network interceptor.

    Clone the network interceptor repository,
    build it and run it. This function blocks execution.
    """
    logger.info("cloning interceptor repository")
    Repo.clone_from(
        "git@gitlab.ewi.tudelft.nl:cse2000-software-project/2023-2024/cluster-q/13d/xrpl-packet"
        "-interceptor.git",
        ".temp-interceptor",
    )

    logger.info("building .temp-interceptor")
    build_process = subprocess.run(
        "cargo build",
        shell=True,
        capture_output=True,
        cwd=".temp-interceptor",
    )
    build_process.check_returncode()
    logger.info("build succeeded")

    run_process = subprocess.Popen(
        "cargo run",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=".temp-interceptor",
    )
    logger.info("packet interceptor started")
    run_process.communicate()


def on_exc(func, path, exc_info):
    """
    Error handler for ``shutil.rmtree``.

    From: https://stackoverflow.com/a/2656405

    If the error is due to an access error (read only file)
    it attempts to add write permission and then retries.

    If the error is for another reason it re-raises the error.

    Usage : ``shutil.rmtree(path, onerror=onerror)``
    """
    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR)
        func(path)
    else:
        raise
