"""
FastAPI service: REST bridge between BSV3.2 desk/app and Binance USD-M Futures.
Mirrors mt5_trading_system/python/main.py API surface on port 8766.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from binance_connector import BinanceConnector, config_from_env
from position_manager import PositionManager

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("binance_api")

app = FastAPI(title="Bilshenz Binance Bridge", version="1.0.0", docs_url=None, redoc_url=None, openapi_url=None)

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://127.0.0.1:8791").split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)

connector = BinanceConnector(config_from_env())
pos_mgr = PositionManager(connector)
pos_mgr.start()


class LoginBody(BaseModel):
    api_key: str = Field(..., min_length=1, max_length=128)
    api_secret: str = Field(..., min_length=1, max_length=128)
    testnet: bool = True


class OrderBody(BaseModel):
    symbol: str = Field("XAUUSDT", max_length=20, pattern=r"^[A-Za-z0-9]+$")
    side: str = Field("BUY", pattern=r"^(BUY|SELL)$")
    volume: float = Field(0.001, ge=0.0001, le=1000.0)
    sl: float | None = Field(None, ge=0)
    tp: float | None = Field(None, ge=0)
    magic: int = Field(77002002, ge=0)


@app.get("/ping")
def ping():
    st = connector.status_snapshot()
    return {"pong": True, "connected": bool(st.get("connected"))}


@app.get("/health")
def health():
    mode = "paper" if connector.cfg.paper else ("testnet" if connector.cfg.testnet else "live")
    return {"ok": True, "service": "bilshenz-binance-bridge", "mode": mode}


@app.post("/api/login")
def api_login(body: LoginBody):
    connector.configure(body.api_key, body.api_secret, body.testnet)
    snap = connector.status_snapshot()
    if not snap.get("connected"):
        raise HTTPException(status_code=401, detail="Binance login failed — check API key/secret and IP whitelist")
    return {"ok": True, "account": snap.get("account"), "mode": snap.get("mode")}


@app.post("/api/attach")
def api_attach():
    """Use env-configured credentials (no body)."""
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
    connector.configure("", "")
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
    if from_ms is not None and to_ms is not None:
        bars = connector.bars_m30_range(symbol, from_ms, to_ms)
    else:
        bars = connector.bars_m30(symbol, count)
    if not bars:
        raise HTTPException(status_code=503, detail="No bars — check symbol or API")
    if connector.cfg.paper and bars:
        from paper_simulator import paper_store

        last = bars[-1]
        paper_store.set_tick(symbol, last["c"] - 0.05, last["c"] + 0.05)
    return {"symbol": symbol.upper(), "timeframe": "M30", "bars": bars}


@app.get("/api/tick/{symbol}")
def api_tick(symbol: str):
    t = connector.tick(symbol)
    if t is None:
        raise HTTPException(status_code=503, detail="No tick")
    if connector.cfg.paper:
        from paper_simulator import paper_store

        paper_store.set_tick(symbol, t["bid"], t["ask"])
    return t


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
