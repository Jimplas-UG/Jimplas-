#!/usr/bin/env python3
"""Unit test: 15m tick scanner — 5% gain then 0.7% retrace → pending."""
from __future__ import annotations

import os
import sys
import time
from types import SimpleNamespace

os.environ.setdefault("SCANNER_TF_MIN", "15")
os.environ.setdefault("SCANNER_GAIN_PCT", "5.0")
os.environ.setdefault("SCANNER_RETRACE_PCT", "0.7")
os.environ.setdefault("SCANNER_EXEC", "0")

from momentum_scanner import (  # noqa: E402
    GAIN_THRESHOLD_PCT,
    RETRACE_ENTRY_PCT,
    SCANNER_TF_LABEL,
    STATUS_PENDING,
    STATUS_WATCHING,
    MomentumScanner,
)


class FakeConnector:
    def __init__(self) -> None:
        self.cfg = SimpleNamespace(paper=True, api_key="")
        self._connected = False

    def symbol_spec(self, symbol: str, pip_size: float = 0.01) -> dict:
        return {"stepSize": 0.001, "minQty": 0.001}

    def order_market_leg(self, *args, **kwargs) -> dict:
        return {"ok": True, "fill_price": args[2] if len(args) > 2 else 100.0}


def _ts(minutes_ago: float) -> int:
    return int((time.time() - minutes_ago * 60) * 1000)


def test_15m_gain_then_retrace_pending() -> None:
    sc = MomentumScanner(FakeConnector(), lambda: True)
    sc.load_symbols(["TESTUSDT"])
    sym = "TESTUSDT"
    base = 100.0
    now = time.time()

    # Seed 15m history at base price
    for m in range(16, 0, -1):
        sc.on_tick(sym, base, ts_ms=int((now - m * 60) * 1000))

    # Spike +5.5% on 15m window
    spike = base * 1.055
    sc.on_tick(sym, spike)
    coin = sc._coins[sym]
    assert coin.status == STATUS_WATCHING, f"expected WATCHING got {coin.status}"
    assert coin.best_pct >= GAIN_THRESHOLD_PCT
    assert coin.best_tf == SCANNER_TF_LABEL

    # Retrace 0.8% from peak → pending
    retrace_price = spike * (1.0 - 0.008)
    sc.on_tick(sym, retrace_price)
    assert coin.retrace_pct >= RETRACE_ENTRY_PCT, f"retrace={coin.retrace_pct}"
    assert coin.status == STATUS_PENDING, f"expected PENDING got {coin.status}"

    rows = sc.snapshot_rows()
    row = next((r for r in rows if r["symbol"] == sym), None)
    assert row is not None
    assert row["timeframe"] == SCANNER_TF_LABEL
    print("OK 15m tick: gain>=5% retrace>=0.7% -> PENDING")


if __name__ == "__main__":
    try:
        test_15m_gain_then_retrace_pending()
    except AssertionError as e:
        print("FAIL", e, file=sys.stderr)
        raise SystemExit(1)
