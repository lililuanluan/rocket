"""Helper methods to aid in quickly implementing system-level tests."""

import subprocess

from git import Repo
from loguru import logger
from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.models import ServerInfo


async def fetch_node_info(ws_port: int) -> dict:
    """
    Fetch the node info from the websocket server at a specific port.

    Args:
        ws_port: the websocket server port to retrieve the node info from.

    Returns: A dictionary with the node info response.
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
    """Clone the network interceptor repository, build it and run it. This function blocks."""
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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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
