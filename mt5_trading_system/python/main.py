"""
FastAPI service: REST bridge between Expo app and MetaTrader5 Python API.
Run on the same Windows PC as the MT5 terminal.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from mt5_connector import MT5Connector, MT5Config

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("api")

app = FastAPI(title="Bilshenz MT5 Bridge", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

connector = MT5Connector(MT5Config(path=os.environ.get("MT5_TERMINAL_PATH") or None))
LOGIN_TIMEOUT_SEC = float(os.environ.get("MT5_LOGIN_TIMEOUT_SEC", "45"))
IPC_TIMEOUT_SEC = float(os.environ.get("MT5_IPC_TIMEOUT_SEC", "12"))
KEEPALIVE_SEC = int(os.environ.get("MT5_KEEPALIVE_SEC", "30"))

# MetaTrader5 uses a single named pipe — ALL calls must be serialized
_mt5_lock = threading.Lock()
_ipc_pool = ThreadPoolExecutor(max_workers=1)


def _ipc_call(fn, default=None):
    """Run a connector call on the single IPC thread with a lock to prevent pipe corruption."""
    def _guarded():
        with _mt5_lock:
            return fn()
    try:
        return _ipc_pool.submit(_guarded).result(timeout=IPC_TIMEOUT_SEC)
    except FuturesTimeoutError:
        return default
    except Exception as e:
        log.error("IPC call error: %s", e)
        return default


def _keepalive_loop():
    """Background thread: ping MT5 every 30s, auto-recover if connection drops."""
    while True:
        try:
            time.sleep(KEEPALIVE_SEC)
            snap = _ipc_call(connector.status_snapshot, {"connected": False})
            if not snap.get("connected"):
                log.warning("[keepalive] MT5 not connected — triggering recovery")
                _ipc_call(connector._alive, False)
        except Exception as e:
            log.error("[keepalive] error: %s", e)


_keepalive_thread = threading.Thread(target=_keepalive_loop, daemon=True)
_keepalive_thread.start()


class LoginBody(BaseModel):
    login: int = Field(..., description="MT5 account number")
    password: str
    server: str = Field(..., description="Broker server name (any MT5 broker)")
    path: str | None = Field(None, description="Optional path to terminal64.exe folder")


class OrderBody(BaseModel):
    symbol: str = "XAUUSD"
    side: str = "BUY"
    volume: float = 0.01
    sl: float | None = None
    tp: float | None = None
    magic: int = 77002002


@app.get("/health")
def health():
    return {"ok": True, "service": "bilshenz-mt5-bridge"}


def _login_detail() -> str:
    try:
        import MetaTrader5 as mt5

        err = mt5.last_error()
        if err:
            return f"MT5 login failed ({err}) — open your broker terminal, check login/server/password"
    except Exception:
        pass
    return "MT5 login failed — open MT5, log in manually, or use USE TERMINAL SESSION"


@app.post("/api/attach")
def api_attach():
    """Fast connect when MT5 is already logged in (any broker). No password IPC call."""
    ok = _ipc_call(connector.try_attach_existing, False)
    if not ok:
        raise HTTPException(
            status_code=401,
            detail="No active MT5 session — open your broker terminal and log in, then try again",
        )
    account = _ipc_call(connector.account_info, None)
    return {"ok": True, "account": account, "mode": "terminal_session"}


@app.post("/api/login")
def api_login(body: LoginBody):
    server = (body.server or "").strip()
    if not server:
        raise HTTPException(status_code=400, detail="Broker server name is required")
    if body.login <= 0:
        raise HTTPException(status_code=400, detail="Invalid login number")

    def _do_login() -> bool:
        with _mt5_lock:
            return connector.login(body.login, body.password, server, body.path)

    try:
        ok = _ipc_pool.submit(_do_login).result(timeout=LOGIN_TIMEOUT_SEC)
    except FuturesTimeoutError:
        raise HTTPException(
            status_code=504,
            detail=(
                "MT5 login timed out — open MT5, log in to your broker manually, "
                "then tap USE TERMINAL SESSION or CONNECT again"
            ),
        )
    if not ok:
        raise HTTPException(status_code=401, detail=_login_detail())
    return {"ok": True, "account": _ipc_call(connector.account_info, None)}


@app.post("/api/logout")
def api_logout():
    _ipc_call(connector.shutdown, None)
    return {"ok": True}


@app.get("/api/status")
def api_status():
    snap = _ipc_call(connector.status_snapshot, {"connected": False})
    return snap if isinstance(snap, dict) else {"connected": False}


@app.get("/api/symbol/{symbol}")
def api_resolve_symbol(symbol: str, pip_size: float = 0.1):
    sym = _ipc_call(lambda: connector.resolve_symbol(symbol))
    if sym is None:
        raise HTTPException(status_code=503, detail="Symbol not found on broker")
    spec = _ipc_call(lambda: connector.symbol_spec(symbol, pip_size=pip_size))
    if spec is None:
        return {"requested": symbol, "resolved": sym}
    return {"requested": symbol, "resolved": sym, **spec}


@app.get("/api/bars/{symbol}")
def api_bars(symbol: str, count: int = 320, from_ms: int | None = None, to_ms: int | None = None):
    if from_ms is not None and to_ms is not None:
        bars = _ipc_call(lambda: connector.bars_m30_range(symbol, from_ms, to_ms), [])
    else:
        bars = _ipc_call(lambda: connector.bars_m30(symbol, count), [])
    if not bars:
        raise HTTPException(status_code=503, detail="No bars — login, symbol, or chart history")
    sym = _ipc_call(lambda: connector.resolve_symbol(symbol)) or symbol
    return {"symbol": sym, "timeframe": "M30", "bars": bars}


@app.get("/api/tick/{symbol}")
def api_tick(symbol: str):
    t = _ipc_call(lambda: connector.tick(symbol))
    if t is None:
        raise HTTPException(status_code=503, detail="No tick — login or symbol")
    return t


@app.get("/api/positions")
def api_positions(symbol: str | None = None):
    return {"positions": _ipc_call(lambda: connector.positions(symbol), [])}


@app.post("/api/order")
def api_order(body: OrderBody):
    r = _ipc_call(lambda: connector.order_market(body.symbol, body.side, body.volume, body.sl, body.tp, body.magic), {"ok": False, "error": "IPC timeout"})
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r)
    return r


@app.get("/api/logs")
def api_logs(limit: int = 50):
    return {"deals": _ipc_call(lambda: connector.trade_logs(limit), [])}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8765"))
    uvicorn.run(app, host="0.0.0.0", port=port)
