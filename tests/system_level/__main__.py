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


async def fetch_node_hashes(ws_port: int):
    async with AsyncWebsocketClient(f"ws://localhost:{ws_port}") as client:
        info = ServerInfo()
        ledger_response = await client.request(info)
        if not ledger_response.is_successful():
            print("request failed")
            return None
        await client.close()
        return ledger_response.result.get('info').get('validated_ledger').get('hash')


async def main():
    """Entry point of the system-level test suite."""
    strategy: RandomFuzzer = RandomFuzzer(0, 0, 1, 150)

    t = Thread(target=serve, args=(strategy,))
    t.start()

    Repo.clone_from("git@gitlab.ewi.tudelft.nl:cse2000-software-project/2023-2024/cluster-q/13d/xrpl-packet"
                    "-interceptor.git", ".temp-interceptor")

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

    it = 0
    while it < 50:
        print("starting comparison")
        tasks = [fetch_node_hashes(i.ws_public.port) for i in request_ledger_data.validator_node_list_store]
        node_hashes = await asyncio.gather(*tasks)

        temp = node_hashes[0]
        for node_hash in node_hashes:
            if node_hash != temp:
                print(f"HASHES DIFFER {temp} {node_hash}")
        it += 1
        sleep(1)

    print("test complete")
    (out, err) = run_process.communicate()
    print(out)
    print(err)

    # rmtree(".temp-interceptor")
    t.join()


if __name__ == "__main__":
    asyncio.run(main())
