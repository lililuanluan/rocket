"""Entry point of the system-level test suite, run with `python -m tests.system_level`."""

import asyncio
from time import sleep

from xrpl_controller.strategies import Strategy, RandomFuzzer
from xrpl_controller.packet_server import serve
import xrpl_controller.request_ledger_data as request_ledger_data
from xrpl.asyncio.clients import AsyncWebsocketClient
from xrpl.models import Ledger, Tx, ServerInfo

import subprocess
import docker

from threading import Thread
from git import Repo
from shutil import rmtree


async def main():
    """Entry point of the system-level test suite."""
    strategy: RandomFuzzer = RandomFuzzer(0, 0, 1, 150)

    t = Thread(target=serve, args=(strategy,))
    t.start()

    # Repo.clone_from("git@gitlab.ewi.tudelft.nl:cse2000-software-project/2023-2024/cluster-q/13d/xrpl-packet"
    #                 "-interceptor.git", ".temp-interceptor")

    build_process = subprocess.run(
        "cargo build",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=".temp-interceptor",
    )
    build_process.check_returncode()

    print("build succeeded")

    run_process = subprocess.Popen(
        "cargo run",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=".temp-interceptor",
    )

    while len(request_ledger_data.validator_node_list_store) != 2:
        print(
            f"waiting for nodes to come online... {len(request_ledger_data.validator_node_list_store)}"
        )
        sleep(1)

    async with AsyncWebsocketClient("ws://localhost:61000") as client:
        info = ServerInfo()
        ledger_response = await client.request(info)
        while not ledger_response.is_successful():
            print("request failed")
            sleep(3)
            ledger_response = await client.request(info)
        print(
            f"ledger response: {ledger_response.result.get('info').get('validated_ledger')}"
        )

    (out, err) = run_process.communicate()
    print(out)
    print(err)

    # rmtree(".temp-interceptor")
    t.join()


if __name__ == "__main__":
    asyncio.run(main())
