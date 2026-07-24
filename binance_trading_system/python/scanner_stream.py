"""
Binance USD-M Futures scanner market feed.

Primary: !miniTicker@arr WebSocket.
Fallback: REST /fapi/v1/ticker/price poll — required on some VPS IPs where
mainnet all-market WS connects but never delivers frames (bookTicker/REST still work).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

import websockets
from starlette.websockets import WebSocket, WebSocketDisconnect

log = logging.getLogger("scanner_stream")

MAINNET_WS = "wss://fstream.binance.com/ws"
TESTNET_WS = "wss://stream.binancefuture.com/ws"
MAINNET_REST = "https://fapi.binance.com"
TESTNET_REST = "https://testnet.binancefuture.com"
RECONNECT_MIN_SEC = 0.05
RECONNECT_MAX_SEC = 5.0
REST_POLL_SEC = 1.0
WS_STALL_SEC = 4.0
# Offload on_tick so asyncio can answer Binance WS keepalive pings (prevents 1011 timeouts).
# Single worker + scanner RLock — prevents concurrent ticks from racing strategy state.
_TICK_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="scanner-tick")


def _parse_mini_ticker(msg: dict[str, Any]) -> tuple[str, float, int, float | None, float | None] | None:
    sym = str(msg.get("s") or "").upper()
    try:
        price = float(msg.get("c") or 0)
    except (TypeError, ValueError):
        return None
    if not sym or price <= 0:
        return None
    ts = int(msg.get("E") or msg.get("C") or time.time() * 1000)
    pct_24h: float | None = None
    quote_vol: float | None = None
    if msg.get("P") is not None:
        try:
            pct_24h = float(msg.get("P"))
        except (TypeError, ValueError):
            pct_24h = None
    if msg.get("q") is not None:
        try:
            quote_vol = float(msg.get("q"))
        except (TypeError, ValueError):
            quote_vol = None
    return sym, price, ts, pct_24h, quote_vol


def _fetch_rest_prices(testnet: bool) -> list[tuple[str, float, int, float | None, float | None]]:
    base = TESTNET_REST if testnet else MAINNET_REST
    url = f"{base}/fapi/v1/ticker/price"
    req = urllib.request.Request(url, headers={"User-Agent": "bilshenz-scanner/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        payload = json.loads(resp.read().decode("utf-8", "replace"))
    if not isinstance(payload, list):
        return []
    ts = int(time.time() * 1000)
    out: list[tuple[str, float, int, float | None, float | None]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        sym = str(item.get("symbol") or "").upper()
        try:
            price = float(item.get("price") or 0)
        except (TypeError, ValueError):
            continue
        if not sym.endswith("USDT") or price <= 0:
            continue
        out.append((sym, price, ts, None, None))
    return out


class BinanceScannerStream:
    """Subscribes to !miniTicker@arr and/or REST prices; forwards ticks to MomentumScanner."""

    def __init__(
        self,
        get_testnet: Callable[[], bool],
        on_tick: Callable[[str, float, int, float | None, float | None], None],
        load_symbols: Callable[[], list[str]] | None = None,
        get_snapshot: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self._get_testnet = get_testnet
        self._on_tick = on_tick
        self._load_symbols = load_symbols
        self._get_snapshot = get_snapshot
        self._ws_task: asyncio.Task | None = None
        self._rest_task: asyncio.Task | None = None
        self._running = False
        self._ws_connected = False
        self._rest_active = False
        self._last_error: str | None = None
        self._tick_count = 0
        self._ws_tick_count = 0
        self._rest_tick_count = 0
        self._last_ws_tick_mono = 0.0
        self._clients: set[WebSocket] = set()
        self._last_snapshot: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    def status(self) -> dict[str, Any]:
        return {
            "ws_connected": self._ws_connected,
            "rest_active": self._rest_active,
            "last_error": self._last_error,
            "ticks_received": self._tick_count,
            "ws_ticks": self._ws_tick_count,
            "rest_ticks": self._rest_tick_count,
            "clients": len(self._clients),
        }

    def set_snapshot(self, payload: dict[str, Any] | list) -> None:
        if isinstance(payload, list):
            self._last_snapshot = {"rows": payload, "ts": int(time.time() * 1000)}
        else:
            self._last_snapshot = payload

    async def start(self) -> None:
        if self._ws_task and not self._ws_task.done():
            return
        self._running = True
        self._ws_task = asyncio.create_task(self._run_ws_loop(), name="binance-scanner-ws")
        self._rest_task = asyncio.create_task(self._run_rest_loop(), name="binance-scanner-rest")
        log.info("scanner stream started (ws + rest fallback)")

    async def stop(self) -> None:
        self._running = False
        for task in (self._ws_task, self._rest_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._ws_task = None
        self._rest_task = None
        async with self._lock:
            for ws in list(self._clients):
                try:
                    await ws.close()
                except Exception:
                    pass
            self._clients.clear()
        self._ws_connected = False
        self._rest_active = False

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

    async def _run_ws_loop(self) -> None:
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

    def _ws_is_live(self) -> bool:
        if not self._ws_connected:
            return False
        if self._ws_tick_count <= 0:
            return False
        return (time.monotonic() - self._last_ws_tick_mono) < WS_STALL_SEC

    async def _run_rest_loop(self) -> None:
        """Poll all prices when WS is silent/stalled (common on mainnet from some VPS IPs)."""
        # Give WS a short head start; then poll whenever WS is not delivering.
        await asyncio.sleep(2.0)
        warned = False
        while self._running:
            try:
                if self._ws_is_live():
                    self._rest_active = False
                    await asyncio.sleep(REST_POLL_SEC)
                    continue
                testnet = bool(self._get_testnet())
                loop = asyncio.get_running_loop()
                # Fetch on default pool so HTTP does not block the single tick worker.
                batch = await loop.run_in_executor(None, _fetch_rest_prices, testnet)
                if batch:
                    if not self._rest_active:
                        log.warning(
                            "scanner REST price poll ACTIVE (ws silent) symbols=%s testnet=%s",
                            len(batch),
                            testnet,
                        )
                        warned = True
                    self._rest_active = True
                    self._tick_count += len(batch)
                    self._rest_tick_count += len(batch)
                    await loop.run_in_executor(_TICK_EXECUTOR, self._dispatch_ticks, batch)
                elif not warned:
                    log.warning("scanner REST price poll returned empty")
                    warned = True
            except asyncio.CancelledError:
                raise
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
                self._last_error = f"rest_poll:{e}"
                log.warning("scanner REST price poll failed: %s", e)
            except Exception as e:
                self._last_error = f"rest_poll:{e}"
                log.warning("scanner REST price poll error: %s", e)
            await asyncio.sleep(REST_POLL_SEC)

    def _dispatch_ticks(self, items: list[tuple[str, float, int, float | None, float | None]]) -> None:
        """Runs in a worker thread — must not touch asyncio objects directly."""
        for sym, price, ts, pct_24h, quote_vol in items:
            try:
                self._on_tick(sym, price, ts, pct_24h, quote_vol)
            except Exception as e:
                log.debug("on_tick %s: %s", sym, e)

    async def _connect_and_listen(self) -> None:
        testnet = self._get_testnet()
        base = TESTNET_WS if testnet else MAINNET_WS
        url = f"{base}/!miniTicker@arr"
        log.info("connecting scanner WS %s testnet=%s", url, testnet)
        # Longer ping timeout: under load the loop must still answer keepalives.
        async with websockets.connect(
            url,
            ping_interval=15,
            ping_timeout=60,
            close_timeout=5,
            max_queue=32,
        ) as ws:
            self._ws_connected = True
            self._last_error = None
            log.info("scanner WS connected")
            loop = asyncio.get_running_loop()
            pending: asyncio.Future | None = None
            # Coalesce latest quote per symbol while worker is busy — never drop live prices.
            pending_map: dict[str, tuple[str, float, int, float | None, float | None]] = {}
            stall_deadline = time.monotonic() + WS_STALL_SEC
            while self._running:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                except asyncio.TimeoutError:
                    # Connected but silent → let REST take over; keep socket for late frames.
                    if time.monotonic() > stall_deadline and self._ws_tick_count == 0:
                        self._last_error = "ws_connected_but_silent"
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                raw_items = payload if isinstance(payload, list) else [payload]
                for item in raw_items:
                    if not isinstance(item, dict):
                        continue
                    parsed = _parse_mini_ticker(item)
                    if not parsed:
                        continue
                    sym, price, ts, pct_24h, quote_vol = parsed
                    pending_map[sym] = (sym, price, ts, pct_24h, quote_vol)
                    self._tick_count += 1
                    self._ws_tick_count += 1
                    self._last_ws_tick_mono = time.monotonic()
                if not pending_map:
                    continue
                if pending is not None and not pending.done():
                    continue
                batch = list(pending_map.values())
                pending_map.clear()
                pending = loop.run_in_executor(_TICK_EXECUTOR, self._dispatch_ticks, batch)
