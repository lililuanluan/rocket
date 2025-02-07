"""
A system-level test case.

This test case checks whether the XRPL validator network is able to validate new ledgers
with our software in between
"""

import asyncio
import multiprocessing
from asyncio import sleep
from os import path
from shutil import rmtree

from loguru import logger

from rocket_controller.iteration_type import NoneIteration
from rocket_controller.packet_server import serve
from rocket_controller.strategies.mutation_example import MutationExample
from tests.system_level.base import ConsistencyFailure, LivenessFailure, SystemLevelTest
from tests.system_level.helper import fetch_node_info, on_exc, start_interceptor


class LivenessTest(SystemLevelTest):
    """The test case class that tests our software for liveness bugs."""

    def __init__(self, iterations: int = 3) -> None:
        """
        Initialize the LivenessTest class.

        Args:
            iterations: The amount of iterations to run the test for
                        (~15 seconds per iteration)
        """
        self.iterations = iterations

    def assert_hashes_equal(self, hash_compare: str, node_infos: [dict]) -> None:
        """
        Asserts a hash is equal to all hashes in a dict[].

        Asserts that the ledger hashes in a list of validator
        node info dicts are equal to another hash.

        Args:
            hash_compare: The hash that needs to be compared
            node_infos: The node info dicts containing the hashes to compare
        """
        for node_info in node_infos:
            cur_hash = node_info.get("validated_ledger").get("hash")
            if hash_compare != cur_hash:
                logger.error(
                    f"HASHES DIFFER | first ledger: {hash_compare} second ledger: {cur_hash}"
                )
                self.add_fault(
                    ConsistencyFailure(
                        f"first ledger: {hash_compare} second ledger: {cur_hash}"
                    )
                )

    def assert_hashes_not_equal(self, prev_hash: str, node_infos: [dict]) -> None:
        """
        Asserts that the ledger hashes in a list of validator node info dicts are *not* equal to another hash.

        Args:
            prev_hash: The hash that needs to be not equal to the other hashes
            node_infos: The node info dicts containing the hashes to compare
        """
        for node_info in node_infos:
            cur_hash = node_info.get("validated_ledger").get("hash")
            if prev_hash == cur_hash:
                logger.error(
                    f"LIVENESS CHECK FAILED | old ledger: {prev_hash} current ledger: {cur_hash}"
                )
                self.add_fault(
                    LivenessFailure(
                        f"old ledger: {prev_hash} current ledger: {cur_hash}"
                    )
                )

    async def run(self):
        """The run method containing the test case logic from start to finish."""
        if path.exists(".temp-interceptor"):
            logger.info("'.temp-interceptor' directory exists, removing it...")
            rmtree(".temp-interceptor", onexc=on_exc)

        # Random fuzzer which is not random, it will send every packet without delaying or dropping
        strategy: MutationExample = MutationExample(
            iteration_type=NoneIteration(timeout_seconds=300)
        )

        interceptor_process = multiprocessing.Process(target=start_interceptor)

        server = serve(strategy)
        interceptor_process.start()

        while len(strategy.network.validator_node_list) != 3:
            logger.info(
                f"waiting for nodes to come online... {len(strategy.network.validator_node_list)}"
            )
            await sleep(2)

        logger.info("waiting 30 seconds for nodes to validate first ledger...")

        # TODO: Figure out a better way to wait for validator nodes
        await sleep(30)

        prev_ledger_hash = None
        for i in range(self.iterations):
            logger.info(f"starting test iteration {i}")
            await sleep(15)

            futures = [
                fetch_node_info(p.ws_public.port)
                for p in strategy.network.validator_node_list
            ]
            node_infos = await asyncio.gather(*futures)

            hash_to_compare = node_infos[0].get("validated_ledger").get("hash")

            self.assert_hashes_equal(hash_to_compare, node_infos)
            self.assert_hashes_not_equal(prev_ledger_hash, node_infos)

            prev_ledger_hash = hash_to_compare
            logger.info(
                f"finished test iteration {i} with {len(self.total_failures)} failure(s) total so far"
            )

        if len(self.total_failures) > 0:
            logger.error(f"test failed, found {len(self.total_failures)} failures.")
            for f in self.total_failures:
                logger.info(f)
        else:
            logger.info("test passed")

        interceptor_process.kill()
        rmtree(".temp-interceptor", onexc=on_exc)
        server.stop(5)
