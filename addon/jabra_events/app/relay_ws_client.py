from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any, Awaitable, Callable

import websockets
from websockets.exceptions import ConnectionClosed

from .health import Health

log = logging.getLogger(__name__)

MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]


class RelayWSClient:
    """Auto-reconnecting WebSocket client for the public relay.

    Sends a `hello` frame on connect, periodic `ping` frames to keep the
    connection alive, and dispatches incoming JSON messages to `on_message`.
    """

    def __init__(
        self,
        url: str,
        site_id: str,
        token: str,
        on_message: MessageHandler,
        health: Health,
        ping_interval: float = 25.0,
        initial_backoff: float = 1.0,
        max_backoff: float = 60.0,
    ) -> None:
        self._url = url
        self._site_id = site_id
        self._token = token
        self._on_message = on_message
        self._health = health
        self._ping_interval = ping_interval
        self._initial_backoff = initial_backoff
        self._max_backoff = max_backoff

    async def run(self) -> None:
        backoff = self._initial_backoff
        while True:
            try:
                await self._run_once()
                backoff = self._initial_backoff
            except Exception as exc:
                log.warning("Relay WS loop ended: %s", exc)
            self._health.update(ws_connected=False)
            sleep_for = min(backoff, self._max_backoff) * (0.5 + random.random())
            log.info("Reconnecting to relay in %.1fs", sleep_for)
            await asyncio.sleep(sleep_for)
            backoff = min(backoff * 2, self._max_backoff)

    async def _run_once(self) -> None:
        log.info("Connecting to relay %s", self._url)
        async with websockets.connect(self._url, ping_interval=None) as ws:
            self._health.update(ws_connected=True)
            await ws.send(
                json.dumps(
                    {
                        "action": "hello",
                        "site_id": self._site_id,
                        "token": self._token,
                    }
                )
            )
            log.info("Relay hello sent; awaiting messages")
            pinger = asyncio.create_task(self._ping_loop(ws))
            try:
                async for raw in ws:
                    await self._dispatch(raw)
            finally:
                pinger.cancel()
                try:
                    await pinger
                except (asyncio.CancelledError, ConnectionClosed):
                    pass

    async def _ping_loop(self, ws: websockets.WebSocketClientProtocol) -> None:
        try:
            while True:
                await asyncio.sleep(self._ping_interval)
                await ws.send(json.dumps({"action": "ping"}))
        except ConnectionClosed:
            return

    async def _dispatch(self, raw: Any) -> None:
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            log.warning("Non-JSON message from relay: %r", raw)
            return
        await self._on_message(message)
