"""
Binance Futures user-data WebSocket — order fills, position and balance updates.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable

import websockets
from websockets.exceptions import ConnectionClosed

log = logging.getLogger("user_data_stream")

MAINNET_WS = "wss://fstream.binance.com/ws"
TESTNET_WS = "wss://stream.binancefuture.com/ws"
RECONNECT_MIN_SEC = 1.0
RECONNECT_MAX_SEC = 20.0


class BinanceUserDataStream:
    """Maintains listenKey + user stream; pushes events to connector callbacks."""

    def __init__(
        self,
        connector: Any,
        get_testnet: Callable[[], bool],
        on_event: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        self._connector = connector
        self._get_testnet = get_testnet
        self._on_event = on_event
        self._task: asyncio.Task | None = None
        self._running = False
        self._ws_connected = False
        self._last_error: str | None = None
        self._last_event_ms: int = 0
        self._last_sync_ms: int = 0
        self._listen_key: str | None = None
        self._event_count = 0

    def status(self) -> dict[str, Any]:
        return {
            "ws_connected": self._ws_connected,
            "listen_key_active": bool(self._listen_key),
            "last_error": self._last_error,
            "last_event_ms": self._last_event_ms or None,
            "last_sync_ms": self._last_sync_ms or None,
            "events_received": self._event_count,
        }

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._close_listen_key()

    async def _close_listen_key(self) -> None:
        if not self._listen_key or not self._connector.cfg.api_key:
            return
        key = self._listen_key
        self._listen_key = None
        try:
            await asyncio.to_thread(
                self._connector._request,
                "DELETE",
                "/fapi/v1/listenKey",
                {"listenKey": key},
                signed=True,
            )
        except Exception as e:
            log.debug("listenKey close: %s", e)

    async def _create_listen_key(self) -> str | None:
        if not self._connector.cfg.api_key:
            return None
        try:
            resp = await asyncio.to_thread(
                self._connector._request, "POST", "/fapi/v1/listenKey", signed=True
            )
            key = resp.get("listenKey") if isinstance(resp, dict) else None
            return str(key) if key else None
        except Exception as e:
            self._last_error = str(e)[:200]
            log.warning("listenKey create failed: %s", e)
            return None

    async def _keepalive_loop(self) -> None:
        while self._running and self._listen_key:
            await asyncio.sleep(25 * 60)
            if not self._listen_key:
                break
            try:
                await asyncio.to_thread(
                    self._connector._request,
                    "PUT",
                    "/fapi/v1/listenKey",
                    {"listenKey": self._listen_key},
                    signed=True,
                )
            except Exception as e:
                log.warning("listenKey keepalive: %s", e)

    def _handle_event(self, payload: dict[str, Any]) -> None:
        self._event_count += 1
        self._last_event_ms = int(time.time() * 1000)
        et = str(payload.get("e") or "")
        if et == "ORDER_TRADE_UPDATE":
            o = payload.get("o") or {}
            status = str(o.get("X") or "")
            sym = str(o.get("s") or "").upper()
            if sym and hasattr(self._connector, "invalidate_positions_cache"):
                self._connector.invalidate_positions_cache()
            log.info(
                "USER_WS order %s %s %s status=%s",
                sym,
                o.get("S"),
                o.get("q"),
                status,
            )
        elif et == "ACCOUNT_UPDATE":
            if hasattr(self._connector, "invalidate_positions_cache"):
                self._connector.invalidate_positions_cache()
            self._last_sync_ms = int(time.time() * 1000)
        if self._on_event:
            try:
                self._on_event(payload)
            except Exception as e:
                log.warning("user event callback: %s", e)

    async def _run_loop(self) -> None:
        backoff = RECONNECT_MIN_SEC
        keepalive_task: asyncio.Task | None = None
        while self._running:
            if not self._connector.cfg.api_key or self._connector.cfg.paper:
                await asyncio.sleep(0.25)
                continue
            listen_key = await self._create_listen_key()
            if not listen_key:
                await asyncio.sleep(backoff)
                backoff = min(backoff * 1.5, RECONNECT_MAX_SEC)
                continue
            self._listen_key = listen_key
            base = TESTNET_WS if self._get_testnet() else MAINNET_WS
            url = f"{base}/{listen_key}"
            if keepalive_task:
                keepalive_task.cancel()
            keepalive_task = asyncio.create_task(self._keepalive_loop())
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=30) as ws:
                    self._ws_connected = True
                    self._last_error = None
                    backoff = RECONNECT_MIN_SEC
                    log.info("user data stream connected")
                    async for raw in ws:
                        if not self._running:
                            break
                        try:
                            msg = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if isinstance(msg, dict):
                            self._handle_event(msg)
            except ConnectionClosed as e:
                self._last_error = f"closed:{e.code}"
            except Exception as e:
                self._last_error = str(e)[:200]
                log.warning("user data stream error: %s", e)
            finally:
                self._ws_connected = False
            if not self._running:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.5, RECONNECT_MAX_SEC)
        if keepalive_task:
            keepalive_task.cancel()
