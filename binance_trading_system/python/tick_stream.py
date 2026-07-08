"""
Binance USD-M Futures bookTicker WebSocket — background stream + client fan-out.
Public market data; no API key required.
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

log = logging.getLogger("tick_stream")

MAINNET_WS = "wss://fstream.binance.com/ws"
TESTNET_WS = "wss://stream.binancefuture.com/ws"
MAX_TICK_AGE_SEC = 120.0
RECONNECT_MIN_SEC = 1.0
RECONNECT_MAX_SEC = 30.0


def _parse_book_ticker(msg: dict[str, Any]) -> dict[str, Any] | None:
    sym = str(msg.get("s") or "").upper()
    try:
        bid = float(msg.get("b") or 0)
        ask = float(msg.get("a") or 0)
    except (TypeError, ValueError):
        return None
    if not sym or bid <= 0 or ask <= 0:
        return None
    ts = int(msg.get("E") or msg.get("T") or time.time() * 1000)
    return {"symbol": sym, "bid": bid, "ask": ask, "time": ts, "source": "ws"}


class BinanceTickStream:
    """Maintains live bookTicker cache and pushes ticks to bridge WebSocket clients."""

    def __init__(
        self,
        get_testnet: Callable[[], bool],
        default_symbol: str = "BTCUSDT",
    ) -> None:
        self._get_testnet = get_testnet
        self._symbols: set[str] = {default_symbol.upper()}
        self._ticks: dict[str, tuple[float, dict[str, Any]]] = {}
        self._clients: set[tuple[WebSocket, str]] = set()
        self._task: asyncio.Task | None = None
        self._running = False
        self._ws_connected = False
        self._last_error: str | None = None
        self._lock = asyncio.Lock()

    def status(self) -> dict[str, Any]:
        return {
            "ws_connected": self._ws_connected,
            "last_error": self._last_error,
            "symbols": sorted(self._symbols),
            "cached": sorted(self._ticks.keys()),
        }

    def get_tick(self, symbol: str, max_age_sec: float = 15.0) -> dict[str, Any] | None:
        sym = symbol.upper()
        ent = self._ticks.get(sym)
        if not ent:
            return None
        ts, tick = ent
        if time.time() - ts > max_age_sec:
            return None
        return tick

    def subscribe_symbol(self, symbol: str) -> None:
        sym = symbol.upper()
        if sym not in self._symbols:
            self._symbols.add(sym)
            log.info("tick stream symbol added: %s", sym)

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="binance-tick-ws")
        log.info("tick stream started symbols=%s", sorted(self._symbols))

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
            for ws, _ in list(self._clients):
                try:
                    await ws.close()
                except Exception:
                    pass
            self._clients.clear()
        self._ws_connected = False

    async def serve_client(self, websocket: WebSocket, symbol: str) -> None:
        sym = symbol.upper()
        self.subscribe_symbol(sym)
        await websocket.accept()
        key = (websocket, sym)
        async with self._lock:
            self._clients.add(key)
        cached = self.get_tick(sym, max_age_sec=MAX_TICK_AGE_SEC)
        if cached:
            await websocket.send_json(cached)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        finally:
            async with self._lock:
                self._clients.discard(key)

    async def _run_loop(self) -> None:
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
                log.warning("tick stream disconnected: %s", e)
            if not self._running:
                break
            await asyncio.sleep(backoff)
            backoff = min(RECONNECT_MAX_SEC, backoff * 1.8)

    async def _connect_and_listen(self) -> None:
        testnet = self._get_testnet()
        base = TESTNET_WS if testnet else MAINNET_WS
        syms = sorted(self._symbols)
        if not syms:
            syms = ["XAUUSDT"]
        if len(syms) == 1:
            url = f"{base}/{syms[0].lower()}@bookTicker"
        else:
            streams = "/".join(f"{s.lower()}@bookTicker" for s in syms)
            root = base.rsplit("/ws", 1)[0]
            url = f"{root}/stream?streams={streams}"

        log.info("connecting Binance WS %s testnet=%s", url, testnet)
        async with websockets.connect(url, ping_interval=20, ping_timeout=30, close_timeout=5) as ws:
            self._ws_connected = True
            self._last_error = None
            log.info("Binance WS connected")
            async for raw in ws:
                if not self._running:
                    break
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
                if not isinstance(data, dict):
                    continue
                tick = _parse_book_ticker(data)
                if tick:
                    await self._store_and_broadcast(tick)

    async def _store_and_broadcast(self, tick: dict[str, Any]) -> None:
        sym = tick["symbol"]
        self._ticks[sym] = (time.time(), tick)
        dead: list[tuple[WebSocket, str]] = []
        async with self._lock:
            targets = [(ws, s) for ws, s in self._clients if s == sym]
        for ws, _ in targets:
            try:
                await ws.send_json(tick)
            except Exception:
                dead.append((ws, sym))
        if dead:
            async with self._lock:
                for item in dead:
                    self._clients.discard(item)
