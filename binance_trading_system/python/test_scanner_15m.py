#!/usr/bin/env python3
"""Unit tests: tick scanner — multi-TF entry + recovery long legs."""
from __future__ import annotations

import os
import sys
import time
from types import SimpleNamespace

os.environ.setdefault("SCANNER_GAIN_PCT", "5.0")
os.environ.setdefault("SCANNER_RETRACE_PCT", "0.7")
os.environ.setdefault("SCANNER_LONG1_PCT", "2.0")
os.environ.setdefault("SCANNER_LONG2_PCT", "4.0")
os.environ.setdefault("SCANNER_LONG_PULLBACK_PCT", "0.5")
os.environ.setdefault("SCANNER_EXEC", "0")

from momentum_scanner import (  # noqa: E402
    GAIN_THRESHOLD_PCT,
    LONG1_ADVERSE_PCT,
    LONG2_ADVERSE_PCT,
    LONG_BOTH_PULLBACK_PCT,
    RETRACE_ENTRY_PCT,
    STATUS_LONG1,
    STATUS_LONG2,
    STATUS_PENDING,
    STATUS_SHORT,
    STATUS_WATCHING,
    MomentumScanner,
)


class FakeConnector:
    def __init__(self) -> None:
        self.cfg = SimpleNamespace(paper=True, api_key="")
        self._connected = False
        self.orders: list[dict] = []
        self.closed: list[dict] = []

    def symbol_spec(self, symbol: str, pip_size: float = 0.01) -> dict:
        return {"stepSize": 0.001, "minQty": 0.001}

    def order_market_leg(self, sym, side, qty, **kwargs) -> dict:
        self.orders.append({"sym": sym, "side": side, "qty": qty, **kwargs})
        return {"ok": True}

    def close_leg(self, sym, magic, qty) -> dict:
        self.closed.append({"sym": sym, "magic": magic, "qty": qty})
        return {"ok": True}


def _seed_base(sc: MomentumScanner, sym: str, base: float = 100.0) -> None:
    sc.load_symbols([sym])
    now = time.time()
    for m in range(16, 0, -1):
        sc.on_tick(sym, base, ts_ms=int((now - m * 60) * 1000))


def test_multi_tf_gain_then_retrace_pending() -> None:
    sc = MomentumScanner(FakeConnector(), lambda: True)
    sym = "TESTUSDT"
    base = 100.0
    _seed_base(sc, sym, base)
    spike = base * 1.055
    sc.on_tick(sym, spike)
    coin = sc._coins[sym]
    assert coin.status == STATUS_WATCHING
    assert coin.best_pct >= GAIN_THRESHOLD_PCT
    assert coin.best_tf in ("1m", "3m", "5m", "15m")

    retrace_price = spike * (1.0 - 0.008)
    sc.on_tick(sym, retrace_price)
    assert coin.retrace_pct >= RETRACE_ENTRY_PCT
    assert coin.status == STATUS_PENDING
    print("OK entry: >=5% gain + >=0.7% retrace -> PENDING")


def test_long1_opens_and_pullback_close() -> None:
    conn = FakeConnector()
    sc = MomentumScanner(conn, lambda: True)
    sym = "TESTUSDT"
    entry = 100.0
    sc.load_symbols([sym])
    sc.on_tick(sym, entry)
    coin = sc._coins[sym]
    from momentum_scanner import LegPosition, MAGIC_SHORT, SHORT_LEVERAGE, STATUS_SHORT

    coin.short = LegPosition("SELL", entry, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
    coin.status = STATUS_SHORT

    sc.on_tick(sym, entry * (1.0 + LONG1_ADVERSE_PCT / 100.0 + 0.001))
    assert coin.long1 is not None, "long1 should open at +2%"

    peak = entry * 1.03
    sc.on_tick(sym, peak)
    sc.on_tick(sym, peak * (1.0 - (LONG_BOTH_PULLBACK_PCT + 0.04) / 100.0))
    assert coin.long1 is None, "long1 should close on 0.5% retrace from its peak"
    print("OK long1: opens at +2%, closes on 0.5% retrace")


def test_long2_opens_and_pullback_close() -> None:
    conn = FakeConnector()
    sc = MomentumScanner(conn, lambda: True)
    sym = "TESTUSDT"
    entry = 100.0
    sc.load_symbols([sym])
    sc.on_tick(sym, entry)
    coin = sc._coins[sym]
    from momentum_scanner import LegPosition, MAGIC_SHORT, SHORT_LEVERAGE, STATUS_SHORT

    coin.short = LegPosition("SELL", entry, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
    coin.status = STATUS_SHORT

    sc.on_tick(sym, entry * (1.0 + LONG2_ADVERSE_PCT / 100.0 + 0.001))
    assert coin.long2 is not None, "long2 should open at +4%"

    peak = entry * 1.05
    sc.on_tick(sym, peak)
    sc.on_tick(sym, peak * (1.0 - (LONG_BOTH_PULLBACK_PCT + 0.04) / 100.0))
    assert coin.long2 is None, "long2 should close on 0.5% retrace from its peak"
    print("OK long2: opens at +4%, closes on 0.5% retrace")


if __name__ == "__main__":
    try:
        test_multi_tf_gain_then_retrace_pending()
        test_long1_opens_and_pullback_close()
        test_long2_opens_and_pullback_close()
    except AssertionError as e:
        print("FAIL", e, file=sys.stderr)
        raise SystemExit(1)
