"""
MT5 terminal bridge via official MetaTrader5 Python package.
Requires MetaTrader 5 terminal installed and logged in on Windows.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None  # type: ignore

log = logging.getLogger("mt5_connector")


@dataclass
class MT5Config:
    path: str | None = None  # terminal64.exe folder; None = default


class MT5Connector:
    """Login, quotes, account, orders — with simple reconnect wrapper."""

    def __init__(self, cfg: MT5Config | None = None):
        self.cfg = cfg or MT5Config()
        self._logged_in = False
        self._login = 0
        self._password = ""
        self._server = ""

    def ensure_init(self) -> bool:
        if mt5 is None:
            log.error("MetaTrader5 package not installed")
            return False
        kwargs: dict[str, Any] = {}
        if self.cfg.path:
            kwargs["path"] = self.cfg.path
        if not mt5.initialize(**kwargs):
            log.error("initialize() failed: %s", mt5.last_error())
            return False
        return True

    def login(self, login: int, password: str, server: str, path: str | None = None) -> bool:
        if mt5 is None:
            return False
        if path:
            self.cfg.path = path
        if not self.ensure_init():
            return False
        ok = mt5.login(int(login), password=password, server=server)
        if not ok:
            log.error("login failed: %s", mt5.last_error())
            self._logged_in = False
            return False
        self._logged_in = True
        self._login = int(login)
        self._password = password
        self._server = server
        return True

    def reconnect(self) -> bool:
        if not self._logged_in:
            return False
        mt5.shutdown()
        time.sleep(0.5)
        return self.login(self._login, self._password, self._server)

    def shutdown(self) -> None:
        if mt5:
            mt5.shutdown()
        self._logged_in = False

    def tick(self, symbol: str) -> dict[str, Any] | None:
        if not self._alive():
            return None
        t = mt5.symbol_info_tick(symbol)
        if t is None:
            return None
        return {
            "bid": t.bid,
            "ask": t.ask,
            "last": t.last,
            "time": int(t.time),
            "volume": int(t.volume),
        }

    def account_info(self) -> dict[str, Any] | None:
        if not self._alive():
            return None
        a = mt5.account_info()
        if a is None:
            return None
        return {
            "login": a.login,
            "server": a.server,
            "balance": a.balance,
            "equity": a.equity,
            "margin": a.margin,
            "margin_free": a.margin_free,
            "profit": a.profit,
            "currency": a.currency,
            "trade_allowed": a.trade_allowed,
        }

    def positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        if not self._alive():
            return []
        pos = mt5.positions_get(symbol=symbol) if symbol else mt5.positions_get()
        if pos is None:
            return []
        out: list[dict[str, Any]] = []
        for p in pos:
            out.append(
                {
                    "ticket": p.ticket,
                    "symbol": p.symbol,
                    "type": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                    "volume": p.volume,
                    "price_open": p.price_open,
                    "sl": p.sl,
                    "tp": p.tp,
                    "profit": p.profit,
                    "magic": p.magic,
                }
            )
        return out

    def order_market(
        self,
        symbol: str,
        side: str,
        volume: float,
        sl: float | None = None,
        tp: float | None = None,
        magic: int = 77002002,
        comment: str = "python_bridge",
    ) -> dict[str, Any]:
        if not self._alive():
            return {"ok": False, "error": "not_connected"}
        side_u = side.upper()
        order_type = mt5.ORDER_TYPE_BUY if side_u == "BUY" else mt5.ORDER_TYPE_SELL
        price = mt5.symbol_info_tick(symbol).ask if side_u == "BUY" else mt5.symbol_info_tick(symbol).bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(volume),
            "type": order_type,
            "price": price,
            "magic": int(magic),
            "comment": comment,
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        if sl is not None:
            request["sl"] = float(sl)
        if tp is not None:
            request["tp"] = float(tp)
        r = mt5.order_send(request)
        if r is None:
            return {"ok": False, "error": str(mt5.last_error())}
        return {
            "ok": r.retcode == mt5.TRADE_RETCODE_DONE,
            "retcode": r.retcode,
            "comment": r.comment,
            "order": r.order,
            "deal": r.deal,
        }

    def trade_logs(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self._alive():
            return []
        to = datetime.now(timezone.utc)
        from_ = to - timedelta(days=30)
        deals = mt5.history_deals_get(from_, to)
        if deals is None:
            return []
        rows: list[dict[str, Any]] = []
        for d in deals[-limit:]:
            rows.append(
                {
                    "ticket": d.ticket,
                    "order": d.order,
                    "symbol": d.symbol,
                    "type": d.type,
                    "volume": d.volume,
                    "price": d.price,
                    "profit": d.profit,
                    "time": int(d.time),
                }
            )
        return rows

    def _alive(self) -> bool:
        if mt5 is None or not self._logged_in:
            return False
        t = mt5.terminal_info()
        if t is None or not t.connected:
            self.reconnect()
            t2 = mt5.terminal_info()
            return t2 is not None and t2.connected
        return True
