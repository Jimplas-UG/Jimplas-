"""
FastAPI service: REST bridge between Expo app and MetaTrader5 Python API.
Run on the same Windows PC as the MT5 terminal.
"""

from __future__ import annotations

import logging
import os

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


class LoginBody(BaseModel):
    login: int = Field(..., description="MT5 account number")
    password: str
    server: str = Field(..., description="Broker server name")
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


@app.post("/api/login")
def api_login(body: LoginBody):
    ok = connector.login(body.login, body.password, body.server, body.path)
    if not ok:
        raise HTTPException(status_code=401, detail="MT5 login failed — check terminal is running and credentials")
    return {"ok": True, "account": connector.account_info()}


@app.post("/api/logout")
def api_logout():
    connector.shutdown()
    return {"ok": True}


@app.get("/api/status")
def api_status():
    info = connector.account_info()
    if info is None:
        return {"connected": False}
    return {"connected": True, "account": info}


@app.get("/api/tick/{symbol}")
def api_tick(symbol: str):
    t = connector.tick(symbol)
    if t is None:
        raise HTTPException(status_code=503, detail="No tick — login or symbol")
    return t


@app.get("/api/positions")
def api_positions(symbol: str | None = None):
    return {"positions": connector.positions(symbol)}


@app.post("/api/order")
def api_order(body: OrderBody):
    r = connector.order_market(body.symbol, body.side, body.volume, body.sl, body.tp, body.magic)
    if not r.get("ok"):
        raise HTTPException(status_code=400, detail=r)
    return r


@app.get("/api/logs")
def api_logs(limit: int = 50):
    return {"deals": connector.trade_logs(limit)}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8765"))
    uvicorn.run(app, host="0.0.0.0", port=port)
