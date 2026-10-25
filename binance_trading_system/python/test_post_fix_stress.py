#!/usr/bin/env python3
"""In-process stress and fault checks. No network and no live account."""
from __future__ import annotations

import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))

from execution_engine import ExecutionEngine, ExecutionSignal  # noqa: E402
from momentum_scanner import CoinStrategy, LegPosition, MomentumScanner  # noqa: E402
from test_execution_engine import MockConnector, _signal  # noqa: E402


def test_duplicate_burst_is_one_order() -> None:
    conn = MockConnector()
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    sig = _signal(signal_id="stress_dup")
    first = eng.execute(sig)
    dup = 0
    for _ in range(299):
        r = eng.execute(sig)
        if r.stage == "duplicate":
            dup += 1
    orders = [c for c in conn.calls if c.get("op") == "order"]
    assert first.ok
    assert dup == 299
    assert len(orders) == 1
    print("OK stress duplicate burst: 300 submits, 1 order, 299 duplicates")


def test_distinct_signals_do_not_collapse() -> None:
    conn = MockConnector()
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    for i in range(50):
        r = eng.execute(_signal(signal_id=f"stress_seq_{i}", symbol="TAGUSDT"))
        assert r.ok, r.error
    orders = [c for c in conn.calls if c.get("op") == "order"]
    assert len(orders) == 50
    print("OK stress 50 distinct signals: 50 orders, 0 duplicates")


def test_timeout_retries_same_client_then_stops() -> None:
    conn = MockConnector()
    conn.fail_times = 2
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    r = eng.execute(_signal(signal_id="stress_timeout"))
    orders = [c for c in conn.calls if c.get("op") == "order"]
    ids = {c.get("client_order_id") or c.get("newClientOrderId") for c in orders}
    assert r.ok and r.retry_count == 2
    assert len(orders) == 3
    print("OK stress timeout: 2 failures then 1 fill, client ids", ids or "engine-assigned")


def test_paired_hold_survives_tick_burst() -> None:
    conn = SimpleNamespace(
        cfg=SimpleNamespace(paper=True, api_key="k"),
        _connected=True,
    )
    sc = MomentumScanner(conn, lambda: True)
    coin = CoinStrategy(symbol="LIGHTUSDT", price=0.30)
    coin.short = LegPosition(side="SELL", entry=0.3028, qty=835.0, leverage=5, magic=88001)
    coin.long1 = LegPosition(side="BUY", entry=0.31197, qty=1294.0, leverage=10, magic=88002)
    closes: list[str] = []
    sc._close_all = lambda c, reason, force=False: closes.append(reason) or {"ok": True}  # type: ignore
    for _ in range(100):
        sc._manage_positions(coin)
    assert closes == [], closes
    print("OK stress 100 manage ticks inside the slice: 0 closes")


def test_partition_loss_fires_once_per_breach() -> None:
    conn = SimpleNamespace(
        cfg=SimpleNamespace(paper=True, api_key="k"),
        _connected=True,
    )
    sc = MomentumScanner(conn, lambda: True)
    coin = CoinStrategy(symbol="LIGHTUSDT", price=0.24)
    coin.short = LegPosition(side="SELL", entry=0.3028, qty=835.0, leverage=5, magic=88001)
    coin.long1 = LegPosition(side="BUY", entry=0.31197, qty=2563.0, leverage=10, magic=88002)
    closes: list[str] = []

    def fake_close(c, reason, force=False):
        closes.append(reason)
        c.short = None
        c.long1 = None
        c.long2 = None
        return {"ok": True}

    sc._close_all = fake_close  # type: ignore
    sc._manage_positions(coin)
    sc._manage_positions(coin)
    assert closes == ["PARTITION_LOSS"]
    print("OK stress partition loss: one flatten, second tick does not resend")


def main() -> None:
    t0 = time.perf_counter()
    test_duplicate_burst_is_one_order()
    test_distinct_signals_do_not_collapse()
    test_timeout_retries_same_client_then_stops()
    test_paired_hold_survives_tick_burst()
    test_partition_loss_fires_once_per_breach()
    elapsed = time.perf_counter() - t0
    print(f"test_post_fix_stress: ALL OK in {elapsed:.2f}s")


if __name__ == "__main__":
    main()
