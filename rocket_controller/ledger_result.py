"""This module contains an implementation to log ledger results."""

from time import sleep
import threading
from typing import Any, List
import json
import os
import time

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
        write_pending: bool = True,
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
        last_exc: str | None = None
        # allow a short number of lgrNotFound skips that do not consume the main retry
        lgr_not_found_skips = 0
        max_lgr_not_found_skips = 3
        attempt = 0
        while attempt < retries:
            try:
                with WebsocketClient(f"ws://localhost:{ws_port}") as client:
                    ledger_info = Ledger(ledger_index=ledger_seq)
                    ledger_response = client.request(ledger_info)
                    if not ledger_response.is_successful():
                        # try detect lgrNotFound (ledger not yet available)
                        try:
                            resp_result = ledger_response.result
                            if isinstance(resp_result, dict) and (
                                resp_result.get("error") == "lgrNotFound"
                                or resp_result.get("error_code") == 21
                                or "ledgerNotFound" in str(resp_result.get("error_message", ""))
                            ):
                                lgr_not_found_skips += 1
                                last_exc = "lgrNotFound"
                                if lgr_not_found_skips >= max_lgr_not_found_skips:
                                    # treat as exhausted
                                    break
                                # small backoff for lgrNotFound and do not count against attempt budget
                                backoff = min(30, 1 * (1.5 ** (lgr_not_found_skips - 1)))
                                sleep(backoff)
                                continue
                            else:
                                last_exc = f"unsuccessful_response: {ledger_response}"
                        except Exception:
                            last_exc = f"unsuccessful_response: {ledger_response}"
                        attempt += 1
                    else:
                        ledger = ledger_response.result.get("ledger")
                        if ledger is None:
                            last_exc = "no_ledger_in_response"
                            attempt += 1
                        else:
                            return ledger
            except Exception as e:  # pragma: no cover - network / runtime errors
                last_exc = f"exception: {e!r}"
                attempt += 1

            # Exponential backoff (1s, 1.5^n, ...), capped to 30s
            backoff = min(30, 1 * (1.5 ** max(0, attempt - 1)))
            sleep(backoff)

        # Final failure - write a compact JSONL record near the result CSV if possible
        # Only write when write_pending is True. Retry callers should pass
        # write_pending=False to avoid appending duplicate pending entries.
        if write_pending:
            try:
                payload = {
                    "ts": int(time.time()),
                    "ws_port": ws_port,
                    "node_id": node_id,
                    "ledger_seq": ledger_seq,
                    "attempts": retries,
                    "last_error": last_exc,
                }
                if self.result_logger:
                    result_dir = os.path.dirname(self.result_logger.filepath)
                    pending_file = os.path.join(result_dir, "pending_ledgers.jsonl")
                else:
                    # Fallback to logs root
                    pending_file = os.path.join("./logs", "pending_ledgers.jsonl")

                # Normalize to absolute path so logs show an unambiguous location
                pending_file = os.path.abspath(pending_file)

                # Deduplicate: read existing entries and only append if this key is new.
                existing_keys: set[tuple[int | None, int | None]] = set()
                try:
                    if os.path.exists(pending_file):
                        with open(pending_file, "r") as ef:
                            for line in ef:
                                try:
                                    j = json.loads(line)
                                    existing_keys.add((j.get("ws_port"), j.get("ledger_seq")))
                                except Exception:
                                    continue
                except Exception:
                    existing_keys = set()

                appended = False
                key = (ws_port, ledger_seq)
                if key not in existing_keys:
                    with open(pending_file, "a") as f:
                        f.write(json.dumps(payload) + "\n")
                    appended = True

                # Only emit an ERROR when we actually appended a new pending record.
                # If the pending file already contained this (ws_port, ledger_seq) pair,
                # downgrade the message to DEBUG to avoid log spam from duplicate failures.
                if appended:
                    logger.error(
                        "Could not retrieve ledger {ledger_seq} from ws_port={ws_port} after {retries} attempts. Wrote pending record to {pending_file}",
                        ledger_seq=ledger_seq,
                        ws_port=ws_port,
                        retries=retries,
                        pending_file=pending_file,
                    )
                else:
                    logger.debug(
                        "Pending entry already exists for ledger {ledger_seq} ws_port={ws_port}; not appending",
                        ledger_seq=ledger_seq,
                        ws_port=ws_port,
                    )
            except Exception:  # pragma: no cover - best-effort write
                logger.exception("Failed to write pending ledger entry after repeated fetch failures")

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
        result = self._fetch_ledger(node.ws_private.port, ledger_seq)
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

                # try a short fetch; pass write_pending=False to avoid duplicate appends
                res = self._fetch_ledger(ws_port, ledger_seq, retries=retries, write_pending=False)
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
