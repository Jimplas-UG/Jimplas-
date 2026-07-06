"""
Binance USD-M Futures all-market miniTicker WebSocket for tick scanner.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable

import websockets
from websockets.exceptions import ConnectionClosed
from starlette.websockets import WebSocket, WebSocketDisconnect

log = logging.getLogger("scanner_stream")

MAINNET_WS = "wss://fstream.binance.com/ws"
TESTNET_WS = "wss://stream.binancefuture.com/ws"
RECONNECT_MIN_SEC = 1.0
RECONNECT_MAX_SEC = 30.0


def _parse_mini_ticker(msg: dict[str, Any]) -> tuple[str, float, int, float | None] | None:
    sym = str(msg.get("s") or "").upper()
    try:
        price = float(msg.get("c") or 0)
    except (TypeError, ValueError):
        return None
    if not sym or price <= 0:
        return None
    ts = int(msg.get("E") or msg.get("C") or time.time() * 1000)
    pct_24h: float | None = None
    try:
        if msg.get("P") is not None:
            pct_24h = float(msg.get("P"))
    except (TypeError, ValueError):
        pct_24h = None
    return sym, price, ts, pct_24h


class BinanceScannerStream:
    """Subscribes to !miniTicker@arr and forwards ticks to MomentumScanner."""

    def __init__(
        self,
        get_testnet: Callable[[], bool],
        on_tick: Callable[[str, float, int, float | None], None],
        load_symbols: Callable[[], list[str]] | None = None,
        get_snapshot: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._get_testnet = get_testnet
        self._on_tick = on_tick
        self._load_symbols = load_symbols
        self._get_snapshot = get_snapshot
        self._task: asyncio.Task | None = None
        self._running = False
        self._ws_connected = False
        self._last_error: str | None = None
        self._tick_count = 0
        self._clients: set[WebSocket] = set()
        self._last_snapshot: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    def status(self) -> dict[str, Any]:
        return {
            "ws_connected": self._ws_connected,
            "last_error": self._last_error,
            "ticks_received": self._tick_count,
            "clients": len(self._clients),
        }

    def set_snapshot(self, payload: dict[str, Any] | list) -> None:
        if isinstance(payload, list):
            self._last_snapshot = {"rows": payload, "ts": int(time.time() * 1000)}
        else:
            self._last_snapshot = payload

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="binance-scanner-ws")
        log.info("scanner stream started")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        async with self._lock:
            for ws in list(self._clients):
                try:
                    await ws.close()
                except Exception:
                    pass
            self._clients.clear()
        self._ws_connected = False

    async def serve_client(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._clients.add(websocket)
        snap = None
        if self._get_snapshot:
            try:
                snap = self._get_snapshot()
            except Exception as e:
                log.warning("fresh scanner snapshot on connect: %s", e)
        if not snap and self._last_snapshot:
            snap = self._last_snapshot
        if snap:
            await websocket.send_json({"type": "snapshot", **snap})
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            async with self._lock:
                self._clients.discard(websocket)

    async def broadcast_snapshot(self, payload: dict[str, Any] | list) -> None:
        if isinstance(payload, list):
            payload = {"rows": payload, "ts": int(time.time() * 1000)}
        self._last_snapshot = payload
        wire = {"type": "snapshot", **payload}
        wire_json = json.dumps(wire)
        dead: list[WebSocket] = []
        async with self._lock:
            targets = list(self._clients)
        for ws in targets:
            try:
                await ws.send_text(wire_json)
            except Exception:
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)

    async def _run_loop(self) -> None:
        if self._load_symbols:
            try:
                syms = self._load_symbols()
                log.info("scanner symbol universe: %s USDT pairs", len(syms))
            except Exception as e:
                log.warning("load_symbols: %s", e)
        backoff = RECONNECT_MIN_SEC
        while self._running:
            try:
                await self._connect_and_listen()
                backoff = RECONNECT_MIN_SEC
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self._ws_connected = False
                self._last_error = str(e)
                log.warning("scanner stream disconnected: %s", e)
            if not self._running:
                break
            await asyncio.sleep(backoff)
            backoff = min(RECONNECT_MAX_SEC, backoff * 1.8)

    async def _connect_and_listen(self) -> None:
        testnet = self._get_testnet()
        base = TESTNET_WS if testnet else MAINNET_WS
        url = f"{base}/!miniTicker@arr"
        log.info("connecting scanner WS %s testnet=%s", url, testnet)
        async with websockets.connect(url, ping_interval=20, ping_timeout=30, close_timeout=5) as ws:
            self._ws_connected = True
            self._last_error = None
            log.info("scanner WS connected")
            async for raw in ws:
                if not self._running:
                    break
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                items = payload if isinstance(payload, list) else [payload]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    parsed = _parse_mini_ticker(item)
                    if not parsed:
                        continue
                    sym, price, ts, pct_24h = parsed
                    self._tick_count += 1
                    try:
                        self._on_tick(sym, price, ts, pct_24h)
                    except Exception as e:
                        log.debug("on_tick %s: %s", sym, e)
