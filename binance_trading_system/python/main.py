"""
FastAPI service: REST bridge between BSV3.2 desk/app and Binance USD-M Futures.
Mirrors mt5_trading_system/python/main.py API surface on port 8766.
"""

from __future__ import annotations

import logging
import os
import re
import time
import asyncio
import threading
from collections import defaultdict
from contextlib import asynccontextmanager

from typing import Any

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from binance_connector import BinanceConnector, config_from_env, _truthy
from position_manager import PositionManager
from tick_stream import BinanceTickStream
from momentum_scanner import MomentumScanner
from scanner_stream import BinanceScannerStream
from user_data_stream import BinanceUserDataStream
from pair_isolation import pair_gate
from execution_engine import ExecutionSignal
from leverage_policy import SHORT_LEVERAGE
from app_config import ensure_valid_or_exit, load_settings
from logging_setup import setup_logging
from session_store import clear_binance_session, load_binance_session, save_binance_session

_settings = load_settings()
setup_logging(_settings.log_dir, os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("binance_api")
log.info("Bilshenz env=%s paper=%s testnet=%s", _settings.env, _settings.paper, _settings.testnet)

BRIDGE_TOKEN = _settings.bridge_token or os.environ.get("BRIDGE_TOKEN", "").strip()
_PUBLIC_PATHS = frozenset({"/health", "/ping", "/docs", "/openapi.json"})
# Unsigned Binance market data — safe without bridge token (home M30 feed).
_PUBLIC_QUOTE_PREFIXES = ("/api/tick/", "/api/bars/", "/api/symbol/", "/api/scanner/", "/api/symbols")


def _is_public_quote(path: str) -> bool:
    return any(path.startswith(p) for p in _PUBLIC_QUOTE_PREFIXES)
_SENSITIVE_PATHS = frozenset({"/api/login", "/api/order", "/api/attach", "/api/logout", "/api/margin"})
# Close paths are never rate-limited — emergency manual flatten must always work.
_TRADE_PATHS = frozenset({"/api/close", "/api/close-all", "/api/scanner/close"})
_rate_buckets: dict[str, list[float]] = defaultdict(list)
_DEFAULT_SYMBOL = (os.environ.get("BINANCE_SYMBOL") or "BTCUSDT").strip().upper()


def _rate_ok(client_key: str, max_per_min: int = 20, *, path: str = "") -> bool:
    now = time.time()
    bucket_key = f"{client_key}:{path}" if path else client_key
    window = [t for t in _rate_buckets[bucket_key] if now - t < 60]
    if len(window) >= max_per_min:
        _rate_buckets[bucket_key] = window
        return False
    window.append(now)
    _rate_buckets[bucket_key] = window
    return True


def _rate_limit_key(request: Request) -> str:
    """Per authenticated client — avoids one mobile user blocking others behind desk proxy."""
    token = _token_from_request(request)
    if token:
        return f"tok:{token[:24]}"
    return _client_key(request)


def _client_key(request: Request) -> str:
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _token_from_request(request: Request) -> str:
    token = request.headers.get("X-Bridge-Token", "").strip()
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        token = token or auth[7:].strip()
    if not token:
        token = request.query_params.get("token", "").strip()
    return token


def _bridge_token_ok(request: Request) -> bool:
    if not BRIDGE_TOKEN:
        return True
    return _token_from_request(request) == BRIDGE_TOKEN


def _ws_token_ok(websocket: WebSocket) -> bool:
    if not BRIDGE_TOKEN:
        return True
    token = websocket.headers.get("X-Bridge-Token", "").strip()
    auth = websocket.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        token = token or auth[7:].strip()
    if not token:
        token = websocket.query_params.get("token", "").strip()
    return token == BRIDGE_TOKEN


connector = BinanceConnector(config_from_env())
pos_mgr = PositionManager(connector)
pos_mgr.start()

tick_stream = BinanceTickStream(
    get_testnet=lambda: connector.cfg.testnet,
    default_symbol=_DEFAULT_SYMBOL,
)

_scanner_payload: dict = {}
_app_loop: asyncio.AbstractEventLoop | None = None


def _on_scanner_snapshot(payload: dict | list) -> None:
    global _scanner_payload
    if isinstance(payload, list):
        payload = momentum_scanner.full_snapshot()
    _scanner_payload = payload
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(scanner_stream.broadcast_snapshot(payload))
    except RuntimeError:
        pass


def _flush_scanner_snapshot() -> None:
    """Push fresh exec/session state to REST cache + all scanner WS clients immediately."""
    momentum_scanner.invalidate_session_cache()
    payload = momentum_scanner.full_snapshot()
    global _scanner_payload
    _scanner_payload = payload
    scanner_stream.set_snapshot(payload)
    momentum_scanner._last_broadcast = time.time()
    if _app_loop and _app_loop.is_running():
        asyncio.run_coroutine_threadsafe(scanner_stream.broadcast_snapshot(payload), _app_loop)
    else:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(scanner_stream.broadcast_snapshot(payload))
        except RuntimeError:
            pass


momentum_scanner = MomentumScanner(
    connector=connector,
    get_testnet=lambda: connector.cfg.testnet,
    on_snapshot=_on_scanner_snapshot,
)

scanner_stream = BinanceScannerStream(
    get_testnet=lambda: connector.cfg.testnet,
    on_tick=lambda sym, price, ts, pct_24h=None, quote_vol=None: momentum_scanner.on_tick(
        sym, price, ts, pct_24h, quote_vol
    ),
    load_symbols=lambda: connector.list_usdt_perpetual_symbols(),
    get_snapshot=lambda: momentum_scanner.full_snapshot(),
)

user_data_stream = BinanceUserDataStream(
    connector,
    get_testnet=lambda: connector.cfg.testnet,
    on_event=lambda _evt: pair_gate.touch_sync(),
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _app_loop
    _app_loop = asyncio.get_running_loop()
    await tick_stream.start()

    async def load_scanner_symbols() -> None:
        for attempt in range(4):
            try:
                syms = await asyncio.to_thread(connector.list_usdt_perpetual_symbols)
                if syms:
                    momentum_scanner.load_symbols(syms)
                    log.info("scanner loaded %s USDT perpetual symbols", len(syms))
                    # Seed rolling % from 1m klines so ready-signal logic works without 15m wait.
                    async def _seed() -> None:
                        await asyncio.sleep(2.0)
                        try:
                            n = await asyncio.to_thread(momentum_scanner.seed_history_from_klines)
                            log.info("scanner history seed complete (%s)", n)
                            _flush_scanner_snapshot()
                        except Exception as se:
                            log.warning("scanner history seed failed: %s", se)

                    asyncio.create_task(_seed())
                    return
            except Exception as e:
                log.warning("scanner symbol load attempt %s: %s", attempt + 1, e)
            await asyncio.sleep(2.0 * (attempt + 1))
        momentum_scanner.load_symbols(["BTCUSDT", "ETHUSDT", "BNBUSDT"])
        log.warning("scanner using fallback symbol list (3)")

    async def refresh_24h_loop() -> None:
        # Immediate fill so market overview has live 24h % right after boot.
        try:
            pct_map = await asyncio.to_thread(connector.ticker_24h_map)
            vol_map = await asyncio.to_thread(connector.ticker_24h_volume_map)
            fund_map = await asyncio.to_thread(connector.funding_rate_map)
            n = await asyncio.to_thread(momentum_scanner.apply_24h_pct_map, pct_map)
            nv = await asyncio.to_thread(momentum_scanner.apply_volume_map, vol_map)
            nf = await asyncio.to_thread(momentum_scanner.apply_funding_rate_map, fund_map)
            if n or nv or nf:
                log.info("scanner initial market stats pct=%s vol=%s fund=%s", n, nv, nf)
                _flush_scanner_snapshot()
        except Exception as e:
            log.warning("initial 24h refresh: %s", e)
        while True:
            try:
                await asyncio.sleep(45.0)
                pct_map = await asyncio.to_thread(connector.ticker_24h_map)
                vol_map = await asyncio.to_thread(connector.ticker_24h_volume_map)
                fund_map = await asyncio.to_thread(connector.funding_rate_map)
                n = await asyncio.to_thread(momentum_scanner.apply_24h_pct_map, pct_map)
                nv = await asyncio.to_thread(momentum_scanner.apply_volume_map, vol_map)
                nf = await asyncio.to_thread(momentum_scanner.apply_funding_rate_map, fund_map)
                if n or nv or nf:
                    log.info("scanner refreshed market stats pct=%s vol=%s fund=%s", n, nv, nf)
                    _flush_scanner_snapshot()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.warning("24h refresh loop: %s", e)

    asyncio.create_task(load_scanner_symbols())
    asyncio.create_task(refresh_24h_loop())
    await scanner_stream.start()

    async def start_user_stream() -> None:
        await user_data_stream.start()

    asyncio.create_task(start_user_stream())

    async def restore_persisted_session() -> None:
        if connector._connected:
            return
        if _truthy(os.environ.get("BINANCE_PAPER", "0")):
            connector.cfg.paper = True
            connector.configure(
                os.environ.get("BINANCE_API_KEY", ""),
                os.environ.get("BINANCE_API_SECRET", ""),
                connector.cfg.testnet,
            )
            if connector.status_snapshot().get("connected"):
                log.info("Binance paper session restored from env")
                _flush_scanner_snapshot()
            return
        stored = await asyncio.to_thread(load_binance_session)
        if stored:
            try:
                acct, err = await asyncio.to_thread(
                    _attempt_binance_login,
                    stored["api_key"],
                    stored["api_secret"],
                    bool(stored.get("testnet", True)),
                )
                if acct is not None:
                    log.info("Binance session restored from persisted credentials")
                    _flush_scanner_snapshot()
                    return
                log.warning("persisted Binance session invalid: %s", err)
                await asyncio.to_thread(clear_binance_session)
            except Exception as e:
                log.warning("persisted session restore failed: %s", e)
        # Fall back to env keys when no persisted session
        env_key = os.environ.get("BINANCE_API_KEY", "").strip()
        env_secret = os.environ.get("BINANCE_API_SECRET", "").strip()
        if env_key and env_secret:
            try:
                acct, err = await asyncio.to_thread(
                    _attempt_binance_login, env_key, env_secret, connector.cfg.testnet
                )
                if acct is not None:
                    log.info("Binance session restored from env credentials")
                    _flush_scanner_snapshot()
            except Exception as e:
                log.warning("env session restore failed: %s", e)

    async def startup_session_and_recovery() -> None:
        await restore_persisted_session()
        try:
            snap = connector.status_snapshot(skip_ping=False)
            if snap.get("connected"):
                log.info("scanner ready for execution (Binance session active)")
                _flush_scanner_snapshot()
                pos = connector.positions()
                orders = connector.open_orders()
                log.info("startup recovery: %s open positions, %s open orders", len(pos), len(orders))
        except Exception as e:
            log.warning("scanner exec restore on startup skipped: %s", e)

    asyncio.create_task(startup_session_and_recovery())
    log.info("Binance tick WebSocket stream started")
    yield
    await scanner_stream.stop()
    await tick_stream.stop()
    log.info("Binance tick WebSocket stream stopped")


app = FastAPI(
    title="Bilshenz Binance Bridge",
    version="1.2.1",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        return response


class BridgeAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/ws/"):
            return await call_next(request)
        if (
            BRIDGE_TOKEN
            and path not in _PUBLIC_PATHS
            and not _is_public_quote(path)
            and not _bridge_token_ok(request)
        ):
            return JSONResponse({"detail": "unauthorized"}, status_code=401)
        if path in _TRADE_PATHS:
            return await call_next(request)
        if path in _SENSITIVE_PATHS:
            key = _rate_limit_key(request)
            limit = 8 if path == "/api/order" else 20
            if not _rate_ok(key, limit, path=path):
                return JSONResponse({"detail": "rate limit exceeded"}, status_code=429)
        return await call_next(request)


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(BridgeAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "CORS_ORIGINS",
        "http://127.0.0.1:8791,http://localhost:8081,http://127.0.0.1:8081",
    ).split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Bridge-Token"],
)

_PUBLIC_CACHE_TTL_SEC = float(os.environ.get("BINANCE_PUBLIC_CACHE_TTL", "45"))
_bars_cache: dict[tuple, tuple[float, list]] = {}


class LoginBody(BaseModel):
    api_key: str = Field(..., min_length=1, max_length=128)
    api_secret: str = Field(..., min_length=1, max_length=128)
    testnet: bool = True
    auto_detect_env: bool = True


def _is_key_env_mismatch(err: str) -> bool:
    return bool(re.search(r"invalid api-key|api-key format|signature|permissions|unauthorized", err or "", re.I))


def _login_error_detail(err: str, testnet: bool) -> str:
    msg = err or "Binance login failed"
    if testnet:
        if re.search(r"invalid api-key|api-key format|signature|permissions", msg, re.I):
            msg = (
                f"{msg} — create Futures API keys at testnet.binancefuture.com "
                "(enable Futures + Read; mainnet keys will not work on testnet)"
            )
        else:
            msg = f"{msg} (testnet mode — keys must be from testnet.binancefuture.com)"
    else:
        if re.search(r"invalid api-key|api-key format|signature|permissions", msg, re.I):
            msg = f"{msg} — use mainnet Futures keys from binance.com (testnet keys will not work on mainnet)"
        else:
            msg = f"{msg} (mainnet mode — ensure key is from binance.com, not testnet)"
    return msg


class OrderBody(BaseModel):
    symbol: str = Field(_DEFAULT_SYMBOL, max_length=20, pattern=r"^[A-Za-z0-9]+$")
    side: str = Field("BUY", pattern=r"^(BUY|SELL)$")
    volume: float = Field(0.001, ge=0.0001, le=50_000_000.0)
    sl: float | None = Field(None, ge=0)
    tp: float | None = Field(None, ge=0)
    magic: int = Field(77002002, ge=0)


class CloseBody(BaseModel):
    """Close position leg(s) on symbol."""
    symbol: str = Field(_DEFAULT_SYMBOL, max_length=20, pattern=r"^[A-Za-z0-9]+$")
    position_side: str | None = None
    volume: float | None = Field(None, gt=0)
    close_pair: bool = False


class MarginBody(BaseModel):
    symbol: str = Field(_DEFAULT_SYMBOL, max_length=20, pattern=r"^[A-Za-z0-9]+$")
    margin_type: str = Field("ISOLATED", pattern=r"^ISOLATED$")


@app.get("/ping")
def ping():
    st = connector.status_snapshot()
    return {"pong": True, "connected": bool(st.get("connected"))}


@app.get("/health")
def health():
    """Lightweight liveness — never block on positions / heavy Binance calls."""
    import shutil

    mode = "paper" if connector.cfg.paper else ("testnet" if connector.cfg.testnet else "live")
    connected = bool(getattr(connector, "_connected", False) and connector.cfg.api_key)
    if connector.cfg.paper:
        connected = True
    disk = shutil.disk_usage("/")
    mem: dict = {}
    try:
        import psutil  # optional

        vm = psutil.virtual_memory()
        mem = {
            "ram_used_mb": round(vm.used / 1024 / 1024),
            "ram_total_mb": round(vm.total / 1024 / 1024),
            "ram_pct": vm.percent,
        }
    except Exception:
        pass
    latency_ms = None
    try:
        t0 = time.perf_counter()
        connector.ping()
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    except Exception:
        pass
    return {
        "ok": True,
        "service": "bilshenz-binance-bridge",
        "env": _settings.env,
        "mode": mode,
        "connected": connected,
        "hedge_mode": None,
        "open_positions": None,
        "binance_latency_ms": latency_ms,
        "disk_free_gb": round(disk.free / 1024**3, 2),
        "memory": mem,
        "tick_stream": tick_stream.status(),
        "scanner_stream": scanner_stream.status(),
        "user_data_stream": user_data_stream.status(),
        "scanner": momentum_scanner.status(),
        "pair_isolation": pair_gate.status(
            momentum_scanner._global_active_symbol,
            lambda: connector.positions(),
        ),
    }


@app.get("/api/diagnostics")
def api_diagnostics():
    """Live diagnostics for monitoring dashboard."""
    import shutil

    mem: dict[str, Any] = {}
    cpu_pct = None
    try:
        import psutil

        vm = psutil.virtual_memory()
        mem = {
            "ram_used_mb": round(vm.used / 1024 / 1024),
            "ram_total_mb": round(vm.total / 1024 / 1024),
            "ram_pct": vm.percent,
        }
        cpu_pct = psutil.cpu_percent(interval=0.1)
    except Exception:
        pass
    binance_latency_ms = None
    try:
        t0 = time.perf_counter()
        connector.ping()
        binance_latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    except Exception:
        pass
    disk = shutil.disk_usage("/")
    return {
        "ok": True,
        "ts": int(time.time() * 1000),
        "binance_latency_ms": binance_latency_ms,
        "cpu_pct": cpu_pct,
        "memory": mem,
        "disk_free_gb": round(disk.free / 1024**3, 2),
        "tick_stream": tick_stream.status(),
        "scanner_stream": scanner_stream.status(),
        "user_data_stream": user_data_stream.status(),
        "pair_isolation": pair_gate.status(
            momentum_scanner._global_active_symbol,
            lambda: connector.positions(),
        ),
        "execution": {
            "last_latency_ms": momentum_scanner.status().get("last_exec_latency_ms"),
            "recent_latencies": momentum_scanner.engine.latency_stats()[:8],
            "events": momentum_scanner.engine.events()[:8],
        },
        "scanner": momentum_scanner.status(),
        "connected": bool(getattr(connector, "_connected", False) and connector.cfg.api_key),
    }


@app.get("/api/scanner/snapshot")
def api_scanner_snapshot():
    global _scanner_payload
    if _scanner_payload:
        return {"ok": True, **_scanner_payload}
    payload = momentum_scanner.full_snapshot()
    _scanner_payload = payload
    return {"ok": True, **payload}


class ScannerCloseBody(BaseModel):
    symbol: str = Field(..., min_length=3, max_length=20, pattern=r"^[A-Za-z0-9]+$")


class ScannerExecBody(BaseModel):
    enabled: bool = True


class ScannerRiskBody(BaseModel):
    partition_usd: float = Field(100, gt=0, le=1_000_000)
    short_pct: float = Field(50, gt=0, le=100)
    long1_pct: float = Field(40, gt=0, le=100)
    long2_pct: float = Field(40, gt=0, le=100)


@app.post("/api/scanner/close")
def api_scanner_close(body: ScannerCloseBody):
    return momentum_scanner.close_strategy(body.symbol.upper())


@app.post("/api/scanner/exec")
def api_scanner_exec(body: ScannerExecBody | None = None):
    """Arm or halt scanner entries. Emergency stop from the app sets enabled=false."""
    if body is not None:
        momentum_scanner.set_exec_enabled(body.enabled)
    st = momentum_scanner.status()
    return {
        "ok": True,
        "exec_enabled": st.get("exec_enabled"),
        "can_execute": st.get("can_execute"),
        "exec_block": st.get("exec_block"),
        "user_exec_halted": st.get("user_exec_halted"),
        "env_controlled": st.get("exec_env_controlled"),
    }


@app.post("/api/scanner/risk")
def api_scanner_risk(body: ScannerRiskBody):
    result = momentum_scanner.set_risk_config(
        partition_usd=body.partition_usd,
        short_pct=body.short_pct,
        long1_pct=body.long1_pct,
        long2_pct=body.long2_pct,
    )
    if not result.get("ok", True):
        raise HTTPException(status_code=409, detail=result)
    st = momentum_scanner.status()
    return {
        "ok": True,
        "partition_usd": st.get("partition_usd"),
        "short_partition_pct": st.get("short_partition_pct"),
        "long1_partition_pct": st.get("long1_partition_pct"),
        "long2_partition_pct": st.get("long2_partition_pct"),
        "risk_locked": st.get("risk_locked"),
    }


@app.websocket("/ws/scanner")
async def ws_scanner(websocket: WebSocket):
    if not _ws_token_ok(websocket):
        await websocket.close(code=4401, reason="unauthorized")
        return
    try:
        await scanner_stream.serve_client(websocket)
    except WebSocketDisconnect:
        pass


def _attempt_binance_login(api_key: str, api_secret: str, testnet: bool) -> tuple[dict[str, Any] | None, str | None]:
    t0 = time.perf_counter()
    connector.cfg.paper = False
    connector.configure(api_key, api_secret, testnet)
    try:
        acct = connector.account_info()
        connector._connected = acct is not None
        if acct is not None:
            momentum_scanner.invalidate_session_cache()
            log.info(
                "login ok env=%s latency_ms=%.0f bal=%s",
                "testnet" if testnet else "mainnet",
                (time.perf_counter() - t0) * 1000,
                (acct or {}).get("balance"),
            )
        return acct, None
    except Exception as e:
        connector._connected = False
        log.warning(
            "login failed env=%s latency_ms=%.0f err=%s",
            "testnet" if testnet else "mainnet",
            (time.perf_counter() - t0) * 1000,
            e,
        )
        return None, str(e)


@app.post("/api/login")
def api_login(body: LoginBody):
    """Fast login — time sync + account verify; alt env in one request when enabled."""
    t0 = time.perf_counter()
    resolved_testnet = bool(body.testnet)
    auto_detected = False
    log.info(
        "login attempt key=%s… testnet=%s auto_detect=%s",
        (body.api_key or "")[:6],
        resolved_testnet,
        body.auto_detect_env,
    )
    acct, err = _attempt_binance_login(body.api_key, body.api_secret, resolved_testnet)

    if acct is None and body.auto_detect_env and _is_key_env_mismatch(err or ""):
        alt_acct, alt_err = _attempt_binance_login(body.api_key, body.api_secret, not resolved_testnet)
        if alt_acct is not None:
            acct = alt_acct
            resolved_testnet = not resolved_testnet
            auto_detected = True
        else:
            err = alt_err or err

    if acct is None:
        raise HTTPException(
            status_code=401,
            detail=_login_error_detail(err or "Binance login failed", resolved_testnet),
        )

    threading.Thread(target=connector.warm_order_cache, daemon=True).start()
    save_binance_session(body.api_key, body.api_secret, resolved_testnet)

    def _post_login_seed() -> None:
        try:
            hot = [
                c.symbol
                for c in momentum_scanner._coins.values()
                if c.active() or abs(c.pct_24h) >= 3.0 or c.best_pct >= 1.0
            ][:40]
            momentum_scanner.seed_history_from_klines(hot or None)
        except Exception as e:
            log.warning("post-login seed: %s", e)
        _flush_scanner_snapshot()

    threading.Thread(target=_post_login_seed, daemon=True).start()
    _flush_scanner_snapshot()
    st = momentum_scanner.status()
    log.info(
        "login success total_ms=%.0f can_execute=%s block=%s",
        (time.perf_counter() - t0) * 1000,
        st.get("can_execute"),
        st.get("exec_block"),
    )
    return {
        "ok": True,
        "account": acct,
        "mode": "testnet" if resolved_testnet else "live",
        "testnet": resolved_testnet,
        "auto_detected": auto_detected,
        "exec_enabled": st.get("exec_enabled"),
        "can_execute": st.get("can_execute"),
        "exec_block": st.get("exec_block"),
    }


@app.post("/api/attach")
def api_attach():
    """Use env-configured credentials (no body). Paper mode uses simulated account when BINANCE_PAPER=1."""
    connector.cfg.paper = _truthy(os.environ.get("BINANCE_PAPER", "0"))
    connector.configure(
        os.environ.get("BINANCE_API_KEY", ""),
        os.environ.get("BINANCE_API_SECRET", ""),
        connector.cfg.testnet,
    )
    snap = connector.status_snapshot()
    if not snap.get("connected"):
        raise HTTPException(
            status_code=401,
            detail="Binance not configured — set BINANCE_API_KEY/SECRET or POST /api/login",
        )
    st = momentum_scanner.status()
    _flush_scanner_snapshot()
    return {
        "ok": True,
        "account": snap.get("account"),
        "mode": snap.get("mode", "env"),
        "exec_enabled": st.get("exec_enabled"),
        "can_execute": st.get("can_execute"),
        "exec_block": st.get("exec_block"),
    }


@app.post("/api/logout")
def api_logout():
    prev_testnet = connector.cfg.testnet
    connector.cfg.paper = _truthy(os.environ.get("BINANCE_PAPER", "0"))
    connector.configure("", "", prev_testnet)
    connector._connected = False
    clear_binance_session()
    momentum_scanner.invalidate_session_cache()
    _flush_scanner_snapshot()
    return {"ok": True}


@app.get("/api/symbols")
def api_symbols(refresh: bool = False):
    """All TRADING USDT-M perpetual symbols from Binance exchangeInfo."""
    try:
        syms = connector.list_usdt_perpetual_symbols() if not refresh else connector.list_usdt_perpetual_symbols()
        return {"ok": True, "symbols": syms, "count": len(syms)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)[:200]) from e


@app.get("/api/symbols/{symbol}/validate")
def api_validate_symbol(symbol: str):
    sym = symbol.upper().strip()
    if not sym.endswith("USDT"):
        return {"ok": False, "symbol": sym, "valid": False, "reason": "not_usdt_quote"}
    try:
        eligible = connector.list_usdt_perpetual_symbols()
        valid = sym in eligible
        return {
            "ok": True,
            "symbol": sym,
            "valid": valid,
            "reason": None if valid else "not_listed_or_not_trading",
        }
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e)[:200]) from e


@app.get("/api/status")
def api_status():
    snap = connector.status_snapshot(skip_ping=connector._connected)
    st = momentum_scanner.status()
    return {
        **snap,
        "exec_enabled": st.get("exec_enabled"),
        "can_execute": st.get("can_execute"),
        "exec_block": st.get("exec_block"),
    }


@app.get("/api/symbol/{symbol}")
def api_resolve_symbol(symbol: str, pip_size: float = 0.1):
    try:
        spec = connector.symbol_spec(symbol, pip_size=pip_size)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    return {"requested": symbol, "resolved": spec["symbol"], **spec}


@app.get("/api/bars/{symbol}")
def api_bars(symbol: str, count: int = 320, from_ms: int | None = None, to_ms: int | None = None):
    sym = symbol.upper()
    cache_key = (sym, int(count), from_ms, to_ms)
    now = time.time()
    cached = _bars_cache.get(cache_key)
    if cached and now - cached[0] < _PUBLIC_CACHE_TTL_SEC:
        bars = cached[1]
    else:
        try:
            if from_ms is not None and to_ms is not None:
                bars = connector.bars_m30_range(symbol, from_ms, to_ms)
            else:
                bars = connector.bars_m30(symbol, count)
        except RuntimeError as e:
            log.warning("bars %s count=%s: %s", sym, count, e)
            raise HTTPException(status_code=503, detail=str(e)) from e
        except Exception as e:
            log.exception("bars %s count=%s", sym, count)
            raise HTTPException(status_code=503, detail=f"Bars fetch failed: {e}") from e
        if bars:
            _bars_cache[cache_key] = (now, bars)
    if not bars:
        raise HTTPException(status_code=503, detail="No bars — check symbol or Binance API reachability")
    if connector.cfg.paper and bars:
        from paper_simulator import paper_store

        last = bars[-1]
        paper_store.set_tick(symbol, last["c"] - 0.05, last["c"] + 0.05)
    return {"symbol": symbol.upper(), "timeframe": "M30", "bars": bars}


@app.get("/api/tick/{symbol}")
def api_tick(symbol: str):
    sym = symbol.upper()
    tick_stream.subscribe_symbol(sym)
    ws_tick = tick_stream.get_tick(sym, max_age_sec=30.0)
    if ws_tick:
        if connector.cfg.paper:
            from paper_simulator import paper_store

            paper_store.set_tick(symbol, ws_tick["bid"], ws_tick["ask"])
        return ws_tick
    t = connector.tick(symbol)
    if t is None:
        raise HTTPException(status_code=503, detail="No tick")
    if connector.cfg.paper:
        from paper_simulator import paper_store

        paper_store.set_tick(symbol, t["bid"], t["ask"])
    return t


@app.websocket("/ws/tick/{symbol}")
async def ws_tick(websocket: WebSocket, symbol: str):
    if not _ws_token_ok(websocket):
        await websocket.close(code=4401, reason="unauthorized")
        return
    try:
        await tick_stream.serve_client(websocket, symbol)
    except WebSocketDisconnect:
        pass


@app.get("/api/positions")
def api_positions(symbol: str | None = None):
    try:
        return {"ok": True, "positions": connector.positions(symbol)}
    except Exception as e:
        log.warning("api_positions: %s", e)
        return {"ok": False, "positions": [], "error": str(e)[:200]}


@app.post("/api/order")
def api_order(body: OrderBody):
    if os.environ.get("FORWARD_DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on"):
        raise HTTPException(status_code=403, detail={"ok": False, "error": "FORWARD_DRY_RUN", "dry_run": True})
    sym = body.symbol.upper()
    ok_iso, iso_reason = pair_gate.can_open(
        sym, momentum_scanner._global_active_symbol, lambda: connector.positions()
    )
    if not ok_iso:
        raise HTTPException(status_code=400, detail={"ok": False, "error": iso_reason})
    if pair_gate.is_close_pending(sym):
        raise HTTPException(status_code=409, detail={"ok": False, "error": "close_pending"})
    side_u = body.side.upper()
    if side_u == "BUY":
        raise HTTPException(
            status_code=400,
            detail={
                "ok": False,
                "error": "buy_blocked_short_first_policy",
                "detail": "All trades start with SHORT. Recovery longs are opened by the scanner only.",
            },
        )
    tick = connector.book_ticker(sym)
    if not tick:
        raise HTTPException(status_code=400, detail={"ok": False, "error": f"no tick for {sym}"})
    ref = tick["ask"] if side_u == "BUY" else tick["bid"]
    signal = ExecutionSignal(
        symbol=sym,
        side=side_u,
        quantity=float(body.volume),
        reference_price=float(ref),
        leverage=SHORT_LEVERAGE,
        magic=int(body.magic),
        leg="MANUAL",
        sl=body.sl,
        tp=body.tp,
        signal_id=f"MANUAL_{sym}_{side_u}_{body.magic}",
        signal_ts_ms=int(time.time() * 1000),
        margin_type="ISOLATED",
    )
    r = momentum_scanner.engine.execute(signal, manual=True)
    if not r.ok:
        raise HTTPException(
            status_code=400,
            detail={
                "ok": False,
                "error": r.error,
                "stage": r.stage,
                "binance_code": r.binance_code,
                "latency_ms": r.latency_ms,
            },
        )
    pair_gate.record_order(
        symbol=sym,
        side=side_u,
        order_id=r.order_id,
        latency_ms=r.latency_ms,
        source="manual",
    )
    connector.invalidate_positions_cache()
    return {
        "ok": True,
        "symbol": sym,
        "side": side_u,
        "quantity": body.volume,
        "fill_price": r.fill_price,
        "order_id": r.order_id,
        "client_order_id": r.client_order_id,
        "latency_ms": r.latency_ms,
        "signal_to_ack_ms": r.signal_to_ack_ms,
        "broker": "binance",
    }


@app.post("/api/close")
def api_close(body: CloseBody):
    if os.environ.get("FORWARD_DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on"):
        raise HTTPException(status_code=403, detail={"ok": False, "error": "FORWARD_DRY_RUN", "dry_run": True})
    sym = body.symbol.upper()
    pair_gate.begin_close(sym)
    try:
        if body.close_pair:
            coin = momentum_scanner._coins.get(sym)
            if coin and (coin.short or coin.long1 or coin.long2):
                r = momentum_scanner.close_strategy(sym)
            else:
                r = connector.close_position(sym, None)
            if not r.get("ok"):
                err = r.get("error") or "close_failed"
                raise HTTPException(status_code=400, detail={"ok": False, "error": err, **r})
        elif body.position_side:
            r = momentum_scanner.close_leg_manual(sym, body.position_side, body.volume)
            if not r.get("ok"):
                err = r.get("error") or "close_failed"
                raise HTTPException(status_code=400, detail={"ok": False, "error": err, **r})
        else:
            positions = connector.positions(sym, force=True)
            if len(positions) > 1:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "ok": False,
                        "error": "multiple_legs_open",
                        "detail": "Specify position_side (SHORT/LONG) or close_pair=true",
                        "legs": [
                            {"position_side": p.get("positionSide"), "type": p.get("type"), "volume": p.get("volume")}
                            for p in positions
                        ],
                    },
                )
            if len(positions) == 1:
                ps = str(positions[0].get("positionSide") or ("SHORT" if positions[0].get("type") == "SELL" else "LONG"))
                r = momentum_scanner.close_leg_manual(sym, ps, body.volume)
            else:
                r = connector.close_position(sym, None)
            if not r.get("ok"):
                err = r.get("error") or "close_failed"
                raise HTTPException(status_code=400, detail={"ok": False, "error": err, **r})
        connector.invalidate_positions_cache()
    finally:
        pair_gate.end_close(sym)
    pair_gate.record_order(
        symbol=sym,
        side="CLOSE_PAIR" if body.close_pair else f"CLOSE_{body.position_side or 'LEG'}",
        order_id=(r.get("closed") or [{}])[0].get("order") if r.get("closed") else r.get("order"),
        latency_ms=float(r.get("latency_ms") or 0),
        source="manual",
    )

    def _bg_after_manual_close() -> None:
        try:
            momentum_scanner.reconcile_from_exchange()
            connector.invalidate_positions_cache()
            _flush_scanner_snapshot()
        except Exception as e:
            log.warning("post-close reconcile: %s", e)

    threading.Thread(target=_bg_after_manual_close, daemon=True, name="close-reconcile").start()
    return r


@app.post("/api/close-all")
def api_close_all():
    """Close every open Binance position and reset scanner state."""
    if os.environ.get("FORWARD_DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on"):
        raise HTTPException(status_code=403, detail={"ok": False, "error": "FORWARD_DRY_RUN", "dry_run": True})
    if not connector.cfg.api_key and not connector.cfg.paper:
        raise HTTPException(status_code=401, detail={"ok": False, "error": "not connected"})
    r = connector.close_all_positions()
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r)

    def _bg_after_close_all() -> None:
        try:
            momentum_scanner.reconcile_from_exchange()
            connector.align_isolated_margin_open_symbols()
            connector.invalidate_positions_cache()
            _flush_scanner_snapshot()
        except Exception as e:
            log.warning("post-close-all reconcile: %s", e)

    threading.Thread(target=_bg_after_close_all, daemon=True, name="close-all-reconcile").start()
    return r


@app.post("/api/margin")
def api_margin(body: MarginBody):
    if os.environ.get("FORWARD_DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on"):
        raise HTTPException(status_code=403, detail={"ok": False, "error": "FORWARD_DRY_RUN", "dry_run": True})
    r = connector.set_margin_type(body.margin_type, body.symbol)
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r)
    actual = connector.symbol_margin_type(body.symbol)
    return {**r, "margin_type": actual, "aligned": actual == "ISOLATED"}


@app.get("/api/order/{order_id}")
def api_order_status(order_id: int, symbol: str = _DEFAULT_SYMBOL):
    """Poll order fill status for reconciliation."""
    if not connector.cfg.api_key:
        raise HTTPException(status_code=401, detail="not connected")
    try:
        row = connector._request(
            "GET",
            "/fapi/v1/order",
            {"symbol": symbol.upper(), "orderId": int(order_id)},
            signed=True,
        )
        return {"ok": True, "order": row}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/trade-calendar")
def api_trade_calendar(days: int = 400):
    lim = max(30, min(730, int(days)))
    try:
        return connector.trade_pnl_calendar(lim)
    except Exception as e:
        log.warning("trade_calendar: %s", e)
        return {"ok": False, "total_pnl": 0.0, "days": [], "error": str(e)}


@app.get("/api/logs")
def api_logs(limit: int = 50, symbol: str | None = None):
    lim = max(1, min(200, int(limit)))
    sym = symbol.upper() if symbol else None
    if connector.cfg.paper:
        from paper_simulator import paper_store

        return {"deals": paper_store.recent_deals(lim)}
    if not connector.cfg.api_key:
        return {"deals": [], "note": "not connected"}
    try:
        deals = connector.recent_deals(lim, sym)
        return {"deals": deals, "limit": lim, "symbol": sym}
    except Exception as e:
        log.warning("recent_deals: %s", e)
        return {"deals": [], "error": str(e), "limit": lim}


if __name__ == "__main__":
    import uvicorn

    settings = ensure_valid_or_exit()
    uvicorn.run(app, host=settings.host, port=settings.port)
