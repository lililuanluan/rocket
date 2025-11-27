"""Simple websocket subscriber to listen to rippled "ledger"/"validations" streams.

This is a minimal, best-effort subscriber: for each validator it opens a websocket
connection to the validator's public WS port, subscribes to streams and enqueues
received messages for the Strategy consumer.

This module uses `websockets` (XRPL depends on it already). It runs an asyncio
loop inside a background thread so startup is simple and non-blocking.
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Callable, List, Optional

from rocket_controller.csv_logger import SubscribeEventLogger
import websockets
from loguru import logger
import socket
import time
from datetime import datetime

from rocket_controller.validator_node_info import ValidatorNode


# WebSocket subscriber for validator nodes
class WSSubscriber:
    def __init__(
        self,
        validator_nodes: List[ValidatorNode],
        log_dir: str,
        enqueue_func: Callable[[Any], None],
    ) -> None:
        """Create a WS subscriber.

        Args:
            validator_nodes: list of ValidatorNode (snapshot) to connect to
            enqueue_func: callable taking one argument (the event). Strategy
                currently passes a queue.put function; this code will call it
                inside a try/except to avoid crashing the subscriber loop.
        """
        self.validator_nodes = validator_nodes
        self._thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self._enqueue = enqueue_func
        # subscriber events CSV logger (best-effort; don't fail if import unavailable)
        self.log_dir = log_dir
        self._subscriber_logger = SubscribeEventLogger(sub_directory=self.log_dir)
        self._msg_types = set()
        # Async loop and task tracking (set when thread starts)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._tasks: Optional[List[asyncio.Task]] = None
        self._verbose: threading.Event = threading.Event()
        # asyncio-side stop event (created inside background loop)
        self._async_stop: Optional[asyncio.Event] = None

    def start(self) -> None:
        """Start the subscriber thread (non-blocking).

        The actual websocket handling runs in an asyncio loop inside the
        background thread. start() returns immediately.
        """
        if self._thread and self._thread.is_alive():
            return
        self.stop_event.clear()
        self._verbose.set()
        self._thread = threading.Thread(
            target=self._run, name="WSSubscriberThread", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Signal the subscriber to stop and wait up to `timeout` seconds."""
        # signal stopping to background tasks
        logger.info("WSSubscriber: stopping")
        self.stop_event.set()
        self._verbose.clear()

        # If the background thread has created an asyncio loop, schedule a
        # cooperative shutdown coroutine inside that loop which will set the
        # asyncio.Event to ask listeners to stop, wait a short grace period
        # for them to finish, then cancel any remaining tasks.
        if self._loop:
            try:
                logger.debug("WSSubscriber.stop: scheduling cooperative shutdown in event loop")
                fut = asyncio.run_coroutine_threadsafe(self._shutdown_and_wait(timeout), self._loop)
                fut.result(timeout=timeout + 0.5)
            except Exception:
                logger.debug("WSSubscriber.stop: shutdown future timed out or raised")

        # join the thread so resources are cleaned up before we return
        if self._thread:
            logger.debug("WSSubscriber.stop: joining thread")
            self._thread.join(timeout=timeout)

    def _run(self) -> None:
        try:
            loop = asyncio.new_event_loop()
            self._loop = loop
            asyncio.set_event_loop(loop)
            # create an asyncio.Event inside this loop for cooperative shutdown
            self._async_stop = asyncio.Event()
            try:
                loop.run_until_complete(self._main())
            finally:
                # best-effort shutdown of any pending tasks
                try:
                    pending = asyncio.all_tasks(loop=loop)
                    for t in pending:
                        if not t.done():
                            t.cancel()
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
                except Exception:
                    pass
                try:
                    loop.close()
                except Exception:
                    pass
        except Exception:
            logger.exception("WSSubscriber main loop failed")
        finally:
            self._loop = None
            self._async_stop = None

    async def _main(self) -> None:
        tasks: List[asyncio.Task] = []
        for idx, node in enumerate(self.validator_nodes):
            # Build ordered candidate urls: try public WS first, then admin WS.
            candidates: list[str] = []

            # Try public ws if present
            wa_pub = getattr(node, "ws_public", None)
            if wa_pub is not None:
                try:
                    url_pub = f"ws://{wa_pub.host}:{wa_pub.port}"
                    if url_pub not in candidates:
                        candidates.append(url_pub)
                except Exception:
                    pass

            # ValidatorNode historically stores admin WS in 'ws_private' (typo); support it
            wa = getattr(node, "ws_private", None) or getattr(node, "ws_admin", None)
            if wa is not None:
                try:
                    url_admin = f"ws://{wa.host}:{wa.port}"
                    if url_admin not in candidates:
                        candidates.append(url_admin)
                except Exception:
                    pass

            if not candidates:
                logger.debug(f"Skipping WS subscriber for node {idx}: no ws ports available")
                continue

            # Create a single task per node which will attempt the candidate URLs in order.
            tasks.append(asyncio.create_task(self._listen_node(idx, candidates)))

        if not tasks:
            logger.debug("WSSubscriber: no websocket tasks created")
            return

        # store tasks so cancellation routine can access them
        self._tasks = tasks
        try:
            await asyncio.gather(*tasks)
        finally:
            self._tasks = None

    async def _shutdown_and_wait(self, timeout: float) -> None:
        """Cooperative shutdown coroutine run inside the subscriber loop.

        It sets the loop-local asyncio.Event so listener coroutines can stop
        quickly. It then waits up to `timeout` seconds for tasks to finish on
        their own. Remaining tasks are cancelled and awaited with
        return_exceptions=True.
        """
        try:
            if self._async_stop is None:
                return
            # signal coroutines to stop cooperatively
            self._async_stop.set()

            # allow tasks a short grace period to finish
            tasks = list(self._tasks or [])
            if not tasks:
                return

            done, pending = await asyncio.wait(tasks, timeout=timeout)

            if pending:
                # cancel remaining pending tasks (don't cancel this coroutine)
                for t in pending:
                    try:
                        t.cancel()
                    except Exception:
                        pass
                await asyncio.gather(*pending, return_exceptions=True)
        except Exception:
            logger.exception("WSSubscriber: error during shutdown")

    async def _listen_node(self, node_idx: int, urls: list[str]) -> None:
        """Try a sequence of websocket URLs for a single node until stopped.

        The function will attempt URLs in order (public, then admin). If a URL
        is not reachable it will try the next; when a connection is established
        it reads messages until disconnect and then resumes trying the list.
        """
        # prefer the asyncio-side stop event for cooperative shutdown; fall back
        # to the threading stop event if set from outside.
        def should_stop() -> bool:
            if self._async_stop is not None and self._async_stop.is_set():
                return True
            return self.stop_event.is_set()

        while not should_stop():
            for url in urls:
                if self.stop_event.is_set():
                    break
                try:
                    # Short TCP probe to avoid noisy websocket handshake errors
                    parsed = url.replace("ws://", "").replace("wss://", "")
                    host, port_s = parsed.split(":")
                    port = int(port_s)

                    # Perform a cancellable TCP probe using asyncio.open_connection
                    try:
                        # open_connection is cancellable and won't block the loop
                        reader, writer = await asyncio.wait_for(
                            asyncio.open_connection(host, port), timeout=1.0
                        )
                        try:
                            writer.close()
                            # wait_closed is only available on streams in py3.7+; guard it
                            if hasattr(writer, "wait_closed"):
                                await writer.wait_closed()
                        except Exception:
                            pass
                    except asyncio.CancelledError:
                        # propagate cancellation so shutdown proceeds quickly
                        raise
                    except Exception:
                        # probe failed; try the next candidate URL
                        # logger.debug(f"WSSubscriber: tcp probe failed to {host}:{port}") if self._verbose.is_set() else None
                        continue

                    # Try opening the websocket and process messages until stopped
                    try:
                        async with websockets.connect(url) as ws:
                            # https://xrpl.org/docs/references/http-websocket-apis/public-api-methods/subscription-methods/subscribe
                            subscribe = {
                                "id": f"ws_sub_{node_idx}",
                                "command": "subscribe",
                                "streams": ["ledger", "validations", "peer_status"],
                            }
                            await ws.send(json.dumps(subscribe))
                            logger.info(f"WSSubscriber: subscribed to {url} streams for node {node_idx}")

                            async for raw in ws:
                                _now = datetime.now()
                                if should_stop():
                                    break
                                try:
                                    msg = json.loads(raw) # # {'peerStatusChange', 'validationReceived', 'ledgerClosed', 'response'}
                                    # self._msg_types.add(msg["type"])
                                    # print(self._msg_types)
                                except Exception:
                                    logger.debug(f"WSSubscriber[{node_idx}] raw: {raw!r}")
                                    continue

                                # include node_idx so consumer can attribute the event
                                event = {"node_idx": node_idx, "msg": msg, "time": _now}
                                try:
                                    # self._enqueue may be a queue.put function or similar callable
                                    self._enqueue(event)
                                except Exception:
                                    # avoid crashing the subscriber; drop the message
                                    logger.debug("WSSubscriber: enqueue failed (dropping message)")
                                # Also write a best-effort record to subscriber_events.csv
                                try:
                                    if self._subscriber_logger is not None:
                                        # timestamp in ms, node index and JSON string of message
                                        self._subscriber_logger.log_row([
                                            int(_now.timestamp() * 1000),
                                            node_idx,
                                            json.dumps(msg),
                                        ])
                                except Exception:
                                    # swallow any file/logging errors to keep subscriber running
                                    logger.debug("WSSubscriber: subscriber_events logging failed")
                    except asyncio.CancelledError:
                        # cancellation requested while connecting/processing ws
                        raise
                    except Exception:
                        logger.debug(f"WSSubscriber: connection to {url} failed, will try other candidates", exc_info=True)
                        continue

                except asyncio.CancelledError:
                    return
                except ConnectionRefusedError:
                    # expected during startup; keep quiet and try other candidates
                    logger.debug(f"WSSubscriber: connection refused to {url}") if self._verbose.is_set() else None
                    continue
                except Exception:
                    logger.debug(f"WSSubscriber: connection to {url} failed, will try other candidates", exc_info=True)
                    continue

            # If none of the candidates worked, back off before retrying full list
            # exponential backoff helps reduce noise during runtime and shutdown
            backoff = 0.5
            while not should_stop():
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    return
                # grow backoff but cap it
                backoff = min(backoff * 2, 5.0)
                break
