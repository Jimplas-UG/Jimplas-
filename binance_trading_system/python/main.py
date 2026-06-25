"""
FastAPI service: REST bridge between BSV3.2 desk/app and Binance USD-M Futures.
Mirrors mt5_trading_system/python/main.py API surface on port 8766.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from binance_connector import BinanceConnector, config_from_env, _truthy
from position_manager import PositionManager
from tick_stream import BinanceTickStream

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("binance_api")

BRIDGE_TOKEN = os.environ.get("BRIDGE_TOKEN", "").strip()
_PUBLIC_PATHS = frozenset({"/health", "/ping", "/docs", "/openapi.json"})
# Unsigned Binance market data — safe without bridge token (home M30 feed).
_PUBLIC_QUOTE_PREFIXES = ("/api/tick/", "/api/bars/", "/api/symbol/")


def _is_public_quote(path: str) -> bool:
    return any(path.startswith(p) for p in _PUBLIC_QUOTE_PREFIXES)
_SENSITIVE_PATHS = frozenset({"/api/login", "/api/order", "/api/close", "/api/attach", "/api/logout", "/api/margin"})
_rate_buckets: dict[str, list[float]] = defaultdict(list)
_DEFAULT_SYMBOL = os.environ.get("BINANCE_SYMBOL", "XAUUSDT").upper()


def _rate_ok(client_key: str, max_per_min: int = 20) -> bool:
    now = time.time()
    window = [t for t in _rate_buckets[client_key] if now - t < 60]
    if len(window) >= max_per_min:
        _rate_buckets[client_key] = window
        return False
    window.append(now)
    _rate_buckets[client_key] = window
    return True


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await tick_stream.start()
    log.info("Binance tick WebSocket stream started")
    yield
    await tick_stream.stop()
    log.info("Binance tick WebSocket stream stopped")


app = FastAPI(
    title="Bilshenz Binance Bridge",
    version="1.2.0",
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
        if path in _SENSITIVE_PATHS:
            key = _client_key(request)
            limit = 8 if path == "/api/order" else 12
            if not _rate_ok(key, limit):
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
    symbol: str = Field("XAUUSDT", max_length=20, pattern=r"^[A-Za-z0-9]+$")
    side: str = Field("BUY", pattern=r"^(BUY|SELL)$")
    volume: float = Field(0.001, ge=0.0001, le=1000.0)
    sl: float | None = Field(None, ge=0)
    tp: float | None = Field(None, ge=0)
    magic: int = Field(77002002, ge=0)


class CloseBody(BaseModel):
    symbol: str = Field("XAUUSDT", max_length=20, pattern=r"^[A-Za-z0-9]+$")
    volume: float | None = Field(None, ge=0.0001, le=1000.0)


class MarginBody(BaseModel):
    symbol: str = Field("XAUUSDT", max_length=20, pattern=r"^[A-Za-z0-9]+$")
    margin_type: str = Field("ISOLATED", pattern=r"^(ISOLATED|CROSS)$")


@app.get("/ping")
def ping():
    st = connector.status_snapshot()
    return {"pong": True, "connected": bool(st.get("connected"))}


@app.get("/health")
def health():
    mode = "paper" if connector.cfg.paper else ("testnet" if connector.cfg.testnet else "live")
    return {
        "ok": True,
        "service": "bilshenz-binance-bridge",
        "mode": mode,
        "tick_stream": tick_stream.status(),
    }


@app.post("/api/login")
def api_login(body: LoginBody):
    # Explicit app login must validate real Futures credentials (not paper bypass).
    connector.cfg.paper = False
    connector.configure(body.api_key, body.api_secret, body.testnet)
    connector.sync_server_time(force=True)
    snap = connector.status_snapshot()
    if not snap.get("connected"):
        err = _login_error_detail(snap.get("error") or "Binance login failed", body.testnet)
        raise HTTPException(status_code=401, detail=err)
    try:
        connector._ensure_margin_setup()
    except Exception as e:
        log.warning("post-login margin setup: %s", e)
    return {
        "ok": True,
        "account": snap.get("account"),
        "mode": snap.get("mode"),
        "testnet": bool(body.testnet),
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
    return {"ok": True, "account": snap.get("account"), "mode": snap.get("mode", "env")}


@app.post("/api/logout")
def api_logout():
    prev_testnet = connector.cfg.testnet
    connector.cfg.paper = _truthy(os.environ.get("BINANCE_PAPER", "0"))
    connector.configure("", "", prev_testnet)
    return {"ok": True}


@app.get("/api/status")
def api_status():
    return connector.status_snapshot()


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
    return {"positions": connector.positions(symbol)}


@app.post("/api/order")
def api_order(body: OrderBody):
    if os.environ.get("FORWARD_DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on"):
        raise HTTPException(status_code=403, detail={"ok": False, "error": "FORWARD_DRY_RUN", "dry_run": True})
    r = connector.order_market(body.symbol, body.side, body.volume, body.sl, body.tp, body.magic)
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r)
    return r


@app.post("/api/close")
def api_close(body: CloseBody):
    if os.environ.get("FORWARD_DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on"):
        raise HTTPException(status_code=403, detail={"ok": False, "error": "FORWARD_DRY_RUN", "dry_run": True})
    r = connector.close_position(body.symbol, body.volume)
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r)
    return r


@app.post("/api/margin")
def api_margin(body: MarginBody):
    if os.environ.get("FORWARD_DRY_RUN", "").strip().lower() in ("1", "true", "yes", "on"):
        raise HTTPException(status_code=403, detail={"ok": False, "error": "FORWARD_DRY_RUN", "dry_run": True})
    r = connector.set_margin_type(body.margin_type, body.symbol)
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r)
    return r


@app.get("/api/order/{order_id}")
def api_order_status(order_id: int, symbol: str = "XAUUSDT"):
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


@app.get("/api/logs")
def api_logs(limit: int = 50):
    lim = max(1, min(200, int(limit)))
    if connector.cfg.paper:
        from paper_simulator import paper_store

        return {"deals": paper_store.recent_deals(lim)}
    if not connector.cfg.api_key:
        return {"deals": [], "note": "not connected"}
    try:
        sym = connector.cfg.symbol.upper()
        rows = connector._request(
            "GET",
            "/fapi/v1/userTrades",
            {"symbol": sym, "limit": lim},
            signed=True,
        )
        deals = []
        for t in rows or []:
            side = "BUY" if t.get("buyer") else "SELL"
            deals.append(
                {
                    "ticket": t.get("id"),
                    "symbol": t.get("symbol"),
                    "type": side,
                    "volume": float(t.get("qty", 0)),
                    "price": float(t.get("price", 0)),
                    "profit": float(t.get("realizedPnl", 0)),
                    "time": int(t.get("time", 0)),
                }
            )
        return {"deals": deals, "limit": lim}
    except Exception as e:
        log.warning("userTrades: %s", e)
        return {"deals": [], "error": str(e), "limit": lim}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8766"))
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(app, host=host, port=port)
