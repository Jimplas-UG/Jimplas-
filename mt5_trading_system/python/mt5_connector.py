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

    def resolve_symbol(self, symbol: str) -> str | None:
        """Pick first broker symbol that exists (XAUUSD vs XAUUSDm, etc.)."""
        if not self._alive():
            return None
        import os

        env_sym = (os.environ.get("MT5_SYMBOL") or "").strip()
        base = (symbol or "XAUUSD").strip()
        candidates: list[str] = []
        for s in (env_sym, base, f"{base}m", f"{base}.m", f"{base}_m", "GOLD", "XAUUSDm", "XAUUSD"):
            s = s.strip()
            if s and s not in candidates:
                candidates.append(s)
        for s in candidates:
            info = mt5.symbol_info(s)
            if info is not None:
                if not info.visible:
                    mt5.symbol_select(s, True)
                return s
        return None

    def tick(self, symbol: str) -> dict[str, Any] | None:
        if not self._alive():
            return None
        sym = self.resolve_symbol(symbol) or symbol
        t = mt5.symbol_info_tick(sym)
        if t is None:
            return None
        return {
            "symbol": sym,
            "bid": t.bid,
            "ask": t.ask,
            "last": t.last,
            "time": int(t.time),
            "volume": int(t.volume),
        }

    def symbol_spec(self, symbol: str, pip_size: float = 0.1) -> dict[str, Any] | None:
        """Broker symbol metrics for realistic backtest / sizing (spread, $/pip/lot)."""
        if not self._alive():
            return None
        sym = self.resolve_symbol(symbol) or symbol
        info = mt5.symbol_info(sym)
        if info is None:
            return None
        point = float(info.point) if info.point else 0.0
        spread_pts = int(info.spread) if info.spread is not None else 0
        spread_price = spread_pts * point if point > 0 else 0.0
        tick = mt5.symbol_info_tick(sym)
        if tick is not None and tick.ask > 0 and tick.bid > 0:
            spread_live = max(spread_price, float(tick.ask) - float(tick.bid))
        else:
            spread_live = spread_price
        pip = pip_size if pip_size > 0 else 0.1
        spread_pips = spread_live / pip if pip > 0 else 0.0
        tick_size = float(info.trade_tick_size) if info.trade_tick_size else point
        tick_value = float(info.trade_tick_value) if info.trade_tick_value else 0.0
        usd_per_pip_per_lot: float | None = None
        # tick_value formula under-reports on some demo symbols (e.g. XAUUSD → $1 vs ~$10/lot).
        ref_price = float(tick.ask) if tick is not None and tick.ask > 0 else 0.0
        if ref_price > 0:
            profit = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, sym, 1.0, ref_price, ref_price + pip)
            if profit is not None and profit != 0:
                usd_per_pip_per_lot = abs(float(profit))
        if usd_per_pip_per_lot is None and tick_size > 0 and tick_value > 0:
            usd_per_pip_per_lot = tick_value * (pip / tick_size)
        return {
            "symbol": sym,
            "point": point,
            "digits": int(info.digits),
            "spread_points": spread_pts,
            "spread_pips": round(spread_pips, 2),
            "spread_price": spread_live,
            "pip_size": pip,
            "usd_per_pip_per_lot": round(usd_per_pip_per_lot, 4) if usd_per_pip_per_lot else None,
            "volume_min": float(info.volume_min),
            "volume_step": float(info.volume_step),
            "volume_max": float(info.volume_max),
        }

    def _rates_to_bars(self, rates) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if rates is None:
            return out
        for r in rates:
            out.append(
                {
                    "t": int(r["time"]) * 1000,
                    "o": float(r["open"]),
                    "h": float(r["high"]),
                    "l": float(r["low"]),
                    "c": float(r["close"]),
                }
            )
        return out

    def bars_m30(self, symbol: str, count: int = 320) -> list[dict[str, Any]]:
        if not self._alive():
            return []
        sym = self.resolve_symbol(symbol)
        if not sym:
            return []
        n = max(50, min(2000, int(count)))
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M30, 0, n)
        if rates is None:
            log.warning("copy_rates_from_pos failed: %s", mt5.last_error())
            return []
        return self._rates_to_bars(rates)

    def bars_m30_range(self, symbol: str, from_ms: int, to_ms: int) -> list[dict[str, Any]]:
        """M30 OHLC from broker history (UTC epoch ms). Used for long backtests."""
        if not self._alive():
            return []
        sym = self.resolve_symbol(symbol)
        if not sym:
            return []
        from datetime import datetime, timezone

        t0 = max(0, int(from_ms))
        t1 = max(t0 + 1, int(to_ms))
        dt_from = datetime.fromtimestamp(t0 / 1000, tz=timezone.utc)
        dt_to = datetime.fromtimestamp(t1 / 1000, tz=timezone.utc)
        rates = mt5.copy_rates_range(sym, mt5.TIMEFRAME_M30, dt_from, dt_to)
        if rates is None or len(rates) == 0:
            log.warning("copy_rates_range failed: %s", mt5.last_error())
            return []
        return self._rates_to_bars(rates)

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

    def has_open_position(self, symbol: str, magic: int | None = None) -> bool:
        sym = self.resolve_symbol(symbol) or symbol
        for p in self.positions(sym):
            if magic is None or int(p.get("magic") or 0) == int(magic):
                return True
        return False

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
        sym = self.resolve_symbol(symbol) or symbol
        if self.has_open_position(sym, magic):
            return {"ok": False, "error": "position_already_open"}
        tick = mt5.symbol_info_tick(sym)
        if tick is None:
            return {"ok": False, "error": f"no tick for {sym}"}
        price = tick.ask if side_u == "BUY" else tick.bid
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": sym,
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

    def try_attach_existing(self) -> bool:
        """Use an already-logged-in MT5 terminal (no POST /api/login required)."""
        if mt5 is None:
            return False
        if self._logged_in:
            return True
        if not self.ensure_init():
            return False
        a = mt5.account_info()
        if a is None:
            return False
        self._logged_in = True
        self._login = int(a.login)
        self._server = str(a.server)
        return True

    def _alive(self) -> bool:
        if mt5 is None:
            return False
        if not self._logged_in and not self.try_attach_existing():
            return False
        t = mt5.terminal_info()
        if t is None or not t.connected:
            self.reconnect()
            t2 = mt5.terminal_info()
            return t2 is not None and t2.connected
        return True
