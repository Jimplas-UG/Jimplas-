"""
In-memory paper trading for BSV3.2 Binance migration.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PaperPosition:
    symbol: str
    side: str
    volume: float
    price_open: float
    sl: float | None
    tp: float | None
    magic: int
    opened_at: float = field(default_factory=time.time)


class PaperStore:
    def __init__(self, equity: float = 50_000.0):
        self.equity = equity
        self.balance = equity
        self._positions: list[PaperPosition] = []
        self._last_tick: dict[str, dict[str, float]] = {}
        self._deals: list[dict[str, Any]] = []

    def set_tick(self, symbol: str, bid: float, ask: float) -> None:
        self._last_tick[symbol.upper()] = {"bid": bid, "ask": ask}
        self._check_exits(symbol.upper())

    def _mid(self, symbol: str) -> float | None:
        t = self._last_tick.get(symbol.upper())
        if not t:
            return None
        return (t["bid"] + t["ask"]) / 2

    def _check_exits(self, symbol: str) -> None:
        mid = self._mid(symbol)
        if mid is None:
            return
        remaining: list[PaperPosition] = []
        for p in self._positions:
            if p.symbol != symbol:
                remaining.append(p)
                continue
            hit_sl = p.sl is not None and (
                (p.side == "BUY" and mid <= p.sl) or (p.side == "SELL" and mid >= p.sl)
            )
            hit_tp = p.tp is not None and (
                (p.side == "BUY" and mid >= p.tp) or (p.side == "SELL" and mid <= p.tp)
            )
            if hit_sl or hit_tp:
                pnl = (mid - p.price_open) * p.volume * (1 if p.side == "BUY" else -1)
                self.balance += pnl
                self.equity = self.balance
                self._deals.append(
                    {
                        "ticket": len(self._deals) + 1,
                        "symbol": p.symbol,
                        "type": p.side,
                        "volume": p.volume,
                        "price": mid,
                        "profit": pnl,
                        "time": int(time.time() * 1000),
                    }
                )
            else:
                remaining.append(p)
        self._positions = remaining

    def positions(self, symbol: str | None = None) -> list[dict[str, Any]]:
        sym = symbol.upper() if symbol else None
        out = []
        for i, p in enumerate(self._positions):
            if sym and p.symbol != sym:
                continue
            mid = self._mid(p.symbol) or p.price_open
            pnl = (mid - p.price_open) * p.volume * (1 if p.side == "BUY" else -1)
            out.append(
                {
                    "ticket": i + 1,
                    "symbol": p.symbol,
                    "type": p.side,
                    "volume": p.volume,
                    "price_open": p.price_open,
                    "sl": p.sl or 0,
                    "tp": p.tp or 0,
                    "profit": pnl,
                    "magic": p.magic,
                }
            )
        return out

    def has_open(self, symbol: str, magic: int | None = None) -> bool:
        sym = symbol.upper()
        for p in self._positions:
            if p.symbol != sym:
                continue
            if magic is None or p.magic == magic:
                return True
        return False

    def order_market_leg(
        self,
        symbol: str,
        side: str,
        volume: float,
        sl: float | None,
        tp: float | None,
        magic: int,
    ) -> dict[str, Any]:
        sym = symbol.upper()
        if self.has_open(sym, magic):
            return {"ok": False, "error": "leg_already_open"}
        return self.order_market(sym, side, volume, sl, tp, magic)

    def close_leg(self, symbol: str, magic: int, volume: float | None = None) -> dict[str, Any]:
        sym = symbol.upper()
        remaining: list[PaperPosition] = []
        closed: list[dict[str, Any]] = []
        for p in self._positions:
            if p.symbol != sym or p.magic != magic:
                remaining.append(p)
                continue
            qty = float(volume) if volume is not None else p.volume
            if qty <= 0 or qty > p.volume + 1e-12:
                remaining.append(p)
                continue
            tick = self._last_tick.get(sym)
            if not tick:
                return {"ok": False, "error": "no tick — call set_tick first"}
            fill = tick["bid"] if p.side == "BUY" else tick["ask"]
            pnl = (fill - p.price_open) * qty * (1 if p.side == "BUY" else -1)
            self.balance += pnl
            self.equity = self.balance
            deal_id = len(self._deals) + 1
            self._deals.append(
                {
                    "ticket": deal_id,
                    "symbol": sym,
                    "type": p.side,
                    "volume": qty,
                    "price": fill,
                    "profit": pnl,
                    "time": int(time.time() * 1000),
                    "magic": magic,
                }
            )
            closed.append({"symbol": sym, "side": p.side, "volume": qty, "fill_price": fill, "profit": pnl})
            leftover = p.volume - qty
            if leftover > 1e-12:
                remaining.append(
                    PaperPosition(sym, p.side, leftover, p.price_open, p.sl, p.tp, p.magic)
                )
        if not closed:
            return {"ok": False, "error": "no_open_leg"}
        self._positions = remaining
        return {"ok": True, "closed": closed, "broker": "binance-paper"}

    def order_market(
        self,
        symbol: str,
        side: str,
        volume: float,
        sl: float | None,
        tp: float | None,
        magic: int,
    ) -> dict[str, Any]:
        sym = symbol.upper()
        if self.has_open(sym, magic):
            return {"ok": False, "error": "position_already_open"}
        tick = self._last_tick.get(sym)
        if not tick:
            return {"ok": False, "error": "no tick — call set_tick first"}
        fill = tick["ask"] if side.upper() == "BUY" else tick["bid"]
        intended = fill
        self._positions.append(
            PaperPosition(sym, side.upper(), volume, fill, sl, tp, magic)
        )
        deal_id = len(self._deals) + 1
        self._deals.append(
            {
                "ticket": deal_id,
                "symbol": sym,
                "type": side.upper(),
                "volume": volume,
                "price": fill,
                "profit": 0.0,
                "time": int(time.time() * 1000),
            }
        )
        return {
            "ok": True,
            "symbol": sym,
            "side": side.upper(),
            "volume": volume,
            "intended_price": intended,
            "fill_price": fill,
            "spread_pips": (tick["ask"] - tick["bid"]) / 0.1,
            "slippage_pips": 0.0,
            "latency_ms": 1.0,
            "order": int(time.time()),
            "deal": int(time.time()),
            "broker": "binance-paper",
        }

    def recent_deals(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._deals[-max(1, limit) :]

    def close_position(self, symbol: str | None = None, volume: float | None = None) -> dict[str, Any]:
        sym = (symbol or "BTCUSDT").upper()
        remaining: list[PaperPosition] = []
        closed: list[dict[str, Any]] = []
        for p in self._positions:
            if p.symbol != sym:
                remaining.append(p)
                continue
            qty = float(volume) if volume is not None else p.volume
            if qty <= 0 or qty > p.volume + 1e-12:
                remaining.append(p)
                continue
            tick = self._last_tick.get(sym)
            if not tick:
                return {"ok": False, "error": "no tick — call set_tick first"}
            fill = tick["bid"] if p.side == "BUY" else tick["ask"]
            pnl = (fill - p.price_open) * qty * (1 if p.side == "BUY" else -1)
            self.balance += pnl
            self.equity = self.balance
            deal_id = len(self._deals) + 1
            self._deals.append(
                {
                    "ticket": deal_id,
                    "symbol": sym,
                    "type": p.side,
                    "volume": qty,
                    "price": fill,
                    "profit": pnl,
                    "time": int(time.time() * 1000),
                }
            )
            closed.append(
                {
                    "symbol": sym,
                    "side": p.side,
                    "volume": qty,
                    "fill_price": fill,
                    "profit": pnl,
                }
            )
            leftover = p.volume - qty
            if leftover > 1e-12:
                remaining.append(
                    PaperPosition(sym, p.side, leftover, p.price_open, p.sl, p.tp, p.magic)
                )
        if not closed:
            return {"ok": False, "error": "no_open_position"}
        self._positions = remaining
        return {"ok": True, "closed": closed, "broker": "binance-paper"}

    def close_all_positions(self) -> dict[str, Any]:
        syms = sorted({p.symbol for p in self._positions})
        if not syms:
            return {"ok": True, "closed": [], "symbols": [], "note": "already_flat"}
        all_closed: list[dict[str, Any]] = []
        for sym in syms:
            r = self.close_position(sym, None)
            if r.get("ok"):
                all_closed.extend(r.get("closed") or [])
        return {"ok": True, "closed": all_closed, "symbols": syms, "broker": "binance-paper"}


paper_store = PaperStore()
