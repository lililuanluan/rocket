"""This module contains an implementation to log ledger results."""

from time import sleep
import threading
from typing import Any, List
import json
import os
import time
import subprocess
import shutil

from loguru import logger
from xrpl.clients import WebsocketClient
from xrpl.models import Ledger

from rocket_controller.csv_logger import ResultLogger
from rocket_controller.validator_node_info import ValidatorNode


class LedgerResult:
    """Class for logging ledger results."""

    def __init__(self):
        """Initialize the LedgerResult object."""
        self.result_logger: ResultLogger | None = None

    def new_result_logger(self, log_dir: str, iteration: int):
        """
        Create a new LedgerResult.

        Args:
            log_dir: The directory where the action log of the current iteration resides.
            iteration: The current iteration number.
        """
        self.result_logger = ResultLogger(
            f"{log_dir}/iteration-{iteration}", f"result-{iteration}"
        )

    def _fetch_ledger(
        self,
        ws_port: int,
        ledger_seq: int,
        node_id: int | None = None,
        retries: int = 5,
    ) -> dict[str, Any] | None:
        """
        Fetch the node info from the websocket server at a specific port.

        Args:
            ws_port: The websocket server port to retrieve the node info from.
            ledger_seq: The ledger sequence number to fetch.
            retries: The number of retries to attempt if the request fails.
            node_id: Optional node id (only used for richer logging / JSONL record).

        Returns:
            A dictionary containing the node info if available, None otherwise.
        """

        # If node_id is provided and the docker CLI is available on this host,
        # try a local `docker exec` into the validator container first. This is
        # useful when the controller runs on the same host as the containers
        # and avoids relying on network port mappings.

        if node_id is None or shutil.which("docker") is None:
            logger.warning("Skipping docker exec attempt: node_id is None or docker CLI not found")
            return None
        container = f"validator_{node_id}"
        cmd = [
            "docker",
            "exec",
            "-i",
            container,
            "rippled",
            "ledger",
            str(ledger_seq),
        ]

        for i in range(retries):        
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
                if proc.returncode == 0 and proc.stdout:
                    try:
                        data = json.loads(proc.stdout)
                        # rippled CLI typically returns the payload under result.ledger
                        ledger = None
                        if isinstance(data, dict):
                            ledger = data.get("result", {}).get("ledger")
                        if ledger:
                            return ledger
                    except Exception:
                        logger.debug("Failed to parse rippled CLI JSON output")
                else:
                    logger.debug(f"rippled CLI returned non-zero exit code {proc.returncode} or no output, {proc.stdout}, {proc.stderr}")
            except Exception as e:  # pragma: no cover - environment/runtime
                logger.debug("docker exec attempt failed: %r", e)
            sleep(min(30, 2 ** i))

        return None

    def log_ledger_result(
        self,
        node_id: int,
        ledger_seq: int,
        goal_ledger: int,
        time_to_consensus: float,
        validator_nodes: List[ValidatorNode],
    ):
        """
        Method for logging the ledger results.

        Args:
            node_id: The ID of the node to log the ledger result for.
            ledger_seq: The current ledger count.
            goal_ledger: The configured maximum number of ledgers per iteration.
            time_to_consensus: The time taken to reach consensus.
            validator_nodes: The list of validator nodes to check on.
        """
        node = validator_nodes[node_id]
        result = self._fetch_ledger(node.ws_private.port, ledger_seq, node_id=node_id)
        if result is None:
            logger.error(f"Could not retrieve ledger {ledger_seq} from node {node_id}")
            return

        ledger_index = result.get("ledger_index")
        close_time = result.get("close_time")

        _ledger_index = (
            -1
            if ledger_index is None
            else int(ledger_index)
            if isinstance(ledger_index, (int, float, str))
            and str(ledger_index).isdigit()
            else -1
        )

        _close_time = (
            -1
            if close_time is None
            else int(close_time)
            if isinstance(close_time, (int, float, str)) and str(close_time).isdigit()
            else -1
        )

        _ledger_hash = (
            "NOT FOUND"
            if result.get("ledger_hash") is None
            else str(result.get("ledger_hash"))
        )

        if not self.result_logger:
            logger.error("No result logger configured")
            return

        self.result_logger.log_result(
            node_id,
            ledger_seq,
            goal_ledger,
            time_to_consensus,
            _close_time,
            _ledger_hash,
            _ledger_index,
        )

    def retry_pending(self, result_dir: str | None = None, retries: int = 5, max_attempts: int = 3) -> dict[str, int]:
        """
        Reprocess `pending_ledgers.jsonl` found in the result logger directory (or in ./logs
        when no result logger is configured). Resolved entries are removed from the
        pending file and appended to `pending_ledgers_resolved.jsonl`.

        Returns a small summary dict with counts: {"processed": n, "resolved": m, "remaining": k}
        """
        if self.result_logger and result_dir is None:
            result_dir = os.path.dirname(self.result_logger.filepath)
        if result_dir is None:
            result_dir = "./logs"

        pending_file = os.path.join(result_dir, "pending_ledgers.jsonl")
        resolved_file = os.path.join(result_dir, "pending_ledgers_resolved.jsonl")

        # Before retrying, wait for any in-flight LogLedgerResult threads to finish
        # so we don't race with concurrently-started fetches. Block until they
        # complete (no timeout) to ensure consistent sequential retry behavior.
        for t in threading.enumerate():
            if t.name.startswith("LogLedgerResult"):
                logger.debug(f"Waiting for thread {t.name} to finish before retrying pending entries")
                t.join()

        if not os.path.exists(pending_file):
            return {"processed": 0, "resolved": 0, "remaining": 0}

        processed = 0
        resolved = 0
        remaining_entries: list[dict[str, Any]] = []

        with open(pending_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                processed += 1

                ws_port = entry.get("ws_port")
                ledger_seq = entry.get("ledger_seq")
                entry_attempts = int(entry.get("attempts") or 0)
                entry_node_id = entry.get("node_id")

                # try a short fetch; pass write_pending=False to avoid duplicate appends
                res = self._fetch_ledger(
                    ws_port, ledger_seq, node_id=entry_node_id, retries=retries, write_pending=False
                )
                if res is not None:
                    resolved += 1
                    # append resolved record
                    with open(resolved_file, "a") as rf:
                        rf.write(json.dumps({
                            "ts": int(time.time()),
                            "ws_port": ws_port,
                            "ledger_seq": ledger_seq,
                            "resolved": True,
                        }) + "\n")
                else:
                    entry["attempts"] = entry_attempts + int(retries)
                    entry["last_error"] = entry.get("last_error", "fetch_failed")
                    remaining_entries.append(entry)

        # overwrite pending file with remaining entries
        with open(pending_file, "w") as f:
            for e in remaining_entries:
                f.write(json.dumps(e) + "\n")

        return {"processed": processed, "resolved": resolved, "remaining": len(remaining_entries)}
