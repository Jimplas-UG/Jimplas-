#!/usr/bin/env python3
"""Restart-recovery tests: long-first scanner must adopt live Long / Short1 / Short2."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("SCANNER_LONG_DELAY_MS", "0")
os.environ.setdefault("SCANNER_EXEC", "0")

from momentum_scanner import (  # noqa: E402
    LONG_TP_PCT,
    STATUS_LONG1,
    STATUS_SCANNING,
    STATUS_SHORT,
    MomentumScanner,
)


class LiveConnector:
    def __init__(self, positions: list[dict] | None = None) -> None:
        self.cfg = type("cfg", (), {"paper": False, "api_key": "k", "api_secret": "s", "symbol": "RIFUSDT"})()
        self._connected = True
        self._positions = positions or []
        self.closed: list[dict] = []

    def positions(self, symbol=None, force=False) -> list[dict]:
        if symbol:
            return [p for p in self._positions if p["symbol"] == symbol.upper()]
        return list(self._positions)

    def exchange_short_qty(self, symbol=None) -> float:
        return sum(
            float(p.get("volume") or 0)
            for p in self.positions(symbol)
            if str(p.get("positionSide") or "").upper() == "SHORT"
        )

    def exchange_long_qty(self, symbol=None) -> float:
        return sum(
            float(p.get("volume") or 0)
            for p in self.positions(symbol)
            if str(p.get("positionSide") or "").upper() == "LONG"
        )

    def symbol_spec(self, symbol: str, pip_size: float = 0.01) -> dict:
        return {"stepSize": 0.001, "minQty": 0.001, "minNotional": 5.0}

    def get_symbol_spec(self, symbol: str) -> dict:
        return self.symbol_spec(symbol)

    def invalidate_positions_cache(self) -> None:
        pass

    def cancel_all_orders(self, symbol=None) -> None:
        pass

    def place_tp_market(self, *a, **k) -> dict:
        return {"ok": True}

    def ensure_exchange_leverage(self, symbol, leverage=None) -> bool:
        return True

    def close_position(self, symbol=None, volume=None) -> dict:
        self.closed.append({"symbol": symbol, "volume": volume})
        self._positions = [p for p in self._positions if p["symbol"] != (symbol or "").upper()]
        return {"ok": True, "closed": [{"symbol": symbol}]}

    def status_snapshot(self, **_k) -> dict:
        return {"connected": True}


def _long_pos(symbol="RIFUSDT", entry=0.05, qty=1000.0) -> dict:
    return {
        "symbol": symbol,
        "type": "BUY",
        "positionSide": "LONG",
        "volume": qty,
        "price_open": entry,
    }


def _short_pos(symbol="RIFUSDT", entry=0.049, qty=400.0) -> dict:
    return {
        "symbol": symbol,
        "type": "SELL",
        "positionSide": "SHORT",
        "volume": qty,
        "price_open": entry,
    }


def test_adopt_long_from_empty_scanner() -> None:
    conn = LiveConnector([_long_pos()])
    sc = MomentumScanner(conn, lambda: False)
    sc.load_symbols(["RIFUSDT"])
    coin = sc._coins["RIFUSDT"]
    assert coin.status == STATUS_SCANNING and coin.long1 is None

    out = sc.adopt_open_strategies_from_exchange()
    assert out["adopted_longs"] == 1, out
    assert coin.long1 is not None and coin.long1.side == "BUY"
    assert coin.status == STATUS_LONG1
    assert abs(coin.long1.tp_price - 0.05 * (1 + LONG_TP_PCT / 100.0)) < 1e-12
    print("OK adopt: exchange long -> scanner Long status")


def test_adopt_long_and_short1() -> None:
    conn = LiveConnector([_long_pos(), _short_pos()])
    sc = MomentumScanner(conn, lambda: False)
    sc.load_symbols(["RIFUSDT"])
    coin = sc._coins["RIFUSDT"]
    out = sc.adopt_open_strategies_from_exchange()
    assert out["adopted_longs"] == 1
    assert out["adopted_shorts"] >= 1
    assert coin.long1 is not None
    assert coin.short is not None and coin.status == STATUS_SHORT
    print("OK adopt: long + short1 pair adopted long-first")


def test_adopt_skips_orphan_short_without_long() -> None:
    conn = LiveConnector([_short_pos()])
    sc = MomentumScanner(conn, lambda: False)
    sc.load_symbols(["RIFUSDT"])
    out = sc.adopt_open_strategies_from_exchange()
    assert out["adopted_longs"] == 0
    assert out["adopted_shorts"] == 0
    assert sc._coins["RIFUSDT"].short is None
    print("OK adopt: orphan short is never adopted without long")


def test_reconcile_flattens_orphan_short() -> None:
    conn = LiveConnector([_short_pos()])
    sc = MomentumScanner(conn, lambda: False)
    sc.load_symbols(["RIFUSDT"])
    r = sc.reconcile_from_exchange()
    assert conn.closed, "orphan short must be flattened"
    assert "RIFUSDT" in (r.get("reset_symbols") or [])
    print("OK reconcile: orphan short flattened")


if __name__ == "__main__":
    try:
        test_adopt_long_from_empty_scanner()
        test_adopt_long_and_short1()
        test_adopt_skips_orphan_short_without_long()
        test_reconcile_flattens_orphan_short()
    except AssertionError as e:
        print("FAIL", e, file=sys.stderr)
        raise SystemExit(1)
    print("test_adopt_exchange: ALL OK")
