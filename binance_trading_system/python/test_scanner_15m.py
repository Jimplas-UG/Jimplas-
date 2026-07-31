#!/usr/bin/env python3
"""Unit tests: tick scanner — multi-TF entry + recovery leg order (Short then Long1/Long2)."""
from __future__ import annotations

import os
import sys
import time
import unittest.mock
from types import SimpleNamespace

os.environ.setdefault("SCANNER_GAIN_PCT", "5.0")
os.environ.setdefault("SCANNER_RETRACE_PCT", "0.7")
os.environ.setdefault("SCANNER_LONG1_PCT", "2.0")
os.environ.setdefault("SCANNER_LONG2_PCT", "4.0")
os.environ.setdefault("SCANNER_LONG_PULLBACK_PCT", "0.5")
os.environ.setdefault("SCANNER_SHORT_PULLBACK_PCT", "1.5")
os.environ.setdefault("SCANNER_SHORT_PULLBACK_MFE_PCT", "1.5")
os.environ.setdefault("SCANNER_SMART_EXIT_PCT", "6.0")
os.environ.setdefault("SCANNER_LONG_DELAY_MS", "0")
os.environ.setdefault("SCANNER_EXEC", "1")

from momentum_scanner import (  # noqa: E402
    GAIN_THRESHOLD_PCT,
    LONG1_ADVERSE_PCT,
    LONG2_ADVERSE_PCT,
    LONG_HEDGE_PULLBACK_PCT,
    RETRACE_ENTRY_PCT,
    SHORT_TRAIL_PULLBACK_PCT,
    STATUS_LONG1,
    STATUS_LONG2,
    STATUS_PENDING,
    STATUS_SHORT,
    STATUS_WATCHING,
    MomentumScanner,
)
import momentum_scanner as momentum_scanner_mod  # noqa: E402


def _no_smart_exit():
    return unittest.mock.patch.object(momentum_scanner_mod, "SMART_EXIT_NET_PCT", 0.0)


class FakeConnector:
    def __init__(self) -> None:
        self.cfg = SimpleNamespace(paper=True, api_key="")
        self._connected = False
        self.orders: list[dict] = []
        self.closed: list[dict] = []

    def symbol_spec(self, symbol: str, pip_size: float = 0.01) -> dict:
        return {"stepSize": 0.001, "minQty": 0.001, "minNotional": 5.0}

    def get_symbol_spec(self, symbol: str) -> dict:
        return self.symbol_spec(symbol)

    def prepare_symbol_cached(self, symbol: str, leverage: int, margin_type: str = "ISOLATED") -> None:
        pass

    def place_market_order(self, symbol, side, quantity, **kwargs) -> dict:
        self.orders.append({"sym": symbol, "side": side, "qty": quantity, **kwargs})
        fill = float(kwargs.get("reference_price") or 100.0)
        return {
            "ok": True,
            "fill_price": fill,
            "quantity": quantity,
            "order_id": len(self.orders),
        }

    def place_tp_market(self, *args, **kwargs) -> dict:
        return {"ok": True, "order_id": 999}

    def cancel_all_orders(self, symbol=None) -> None:
        self.closed.append({"cancel_all": symbol})

    def order_market_leg(self, sym, side, qty, **kwargs) -> dict:
        return self.place_market_order(sym, side, qty, **kwargs)

    def close_leg(self, sym, magic, qty) -> dict:
        self.closed.append({"sym": sym, "magic": magic, "qty": qty})
        return {"ok": True}

    def invalidate_positions_cache(self) -> None:
        pass


def _seed_base(sc: MomentumScanner, sym: str, base: float = 100.0) -> None:
    sc.load_symbols([sym])
    now = time.time()
    for m in range(16, 0, -1):
        sc.on_tick(sym, base, ts_ms=int((now - m * 60) * 1000))


def test_multi_tf_gain_then_retrace_pending() -> None:
    prev = os.environ.get("SCANNER_EXEC")
    os.environ["SCANNER_EXEC"] = "0"
    try:
        sc = MomentumScanner(FakeConnector(), lambda: True)
        sym = "TESTUSDT"
        base = 100.0
        _seed_base(sc, sym, base)
        spike = base * 1.055
        sc.on_tick(sym, spike)
        coin = sc._coins[sym]
        assert coin.status == STATUS_WATCHING
        assert coin.pct_15m >= GAIN_THRESHOLD_PCT
        assert coin.best_tf == "15m"

        retrace_price = spike * (1.0 - 0.008)
        sc.on_tick(sym, retrace_price)
        assert coin.retrace_pct >= RETRACE_ENTRY_PCT
        assert (coin.qualifying_pct or 0) >= GAIN_THRESHOLD_PCT
        assert coin.status == STATUS_PENDING
        print("OK entry: 15m >=5% gain + >=0.7% retrace -> PENDING")
    finally:
        if prev is None:
            os.environ.pop("SCANNER_EXEC", None)
        else:
            os.environ["SCANNER_EXEC"] = prev


def test_short_tp_at_2_5_pct() -> None:
    conn = FakeConnector()
    sc = MomentumScanner(conn, lambda: True)
    sym = "TESTUSDT"
    entry = 100.0
    sc.load_symbols([sym])
    sc.on_tick(sym, entry)
    coin = sc._coins[sym]
    from momentum_scanner import LegPosition, MAGIC_SHORT, SHORT_LEVERAGE, SHORT_TP_PCT

    tp = entry * (1.0 - SHORT_TP_PCT / 100.0)
    coin.short = LegPosition("SELL", entry, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, tp)
    coin.short_trough_price = entry
    coin.status = STATUS_SHORT

    sc.on_tick(sym, tp - 0.01)
    assert coin.short is None, "short should close at -2.5% TP"
    print("OK short: TP at -2.5%")


def test_long2_tp_at_2_5_pct() -> None:
    conn = FakeConnector()
    sc = MomentumScanner(conn, lambda: True)
    sym = "TESTUSDT"
    entry = 104.0
    sc.load_symbols([sym])
    sc.on_tick(sym, entry)
    coin = sc._coins[sym]
    from momentum_scanner import (
        LegPosition,
        LONG2_LEVERAGE,
        LONG_TP_PCT,
        MAGIC_LONG2,
        MAGIC_SHORT,
        SHORT_LEVERAGE,
    )

    tp = entry * (1.0 + LONG_TP_PCT / 100.0)
    coin.short = LegPosition("SELL", 100.0, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
    coin.long2 = LegPosition("BUY", entry, 1.0, LONG2_LEVERAGE, MAGIC_LONG2, tp)
    coin.long2_peak_price = entry
    coin.status = STATUS_LONG2

    sc.on_tick(sym, tp + 0.01)
    assert coin.long2 is None, "long2 should close at +2.5% TP"
    print("OK long2: TP at +2.5%")


def test_long1_opens_at_2pct_and_closes_on_half_pct_retrace() -> None:
    with _no_smart_exit():
        conn = FakeConnector()
        sc = MomentumScanner(conn, lambda: True)
        sym = "TESTUSDT"
        entry = 100.0
        sc.load_symbols([sym])
        sc.on_tick(sym, entry)
        coin = sc._coins[sym]
        from momentum_scanner import LegPosition, MAGIC_SHORT, SHORT_LEVERAGE

        coin.short = LegPosition("SELL", entry, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
        coin.short_trough_price = entry
        coin.status = STATUS_SHORT
        coin.short_opened_ms = int(time.time() * 1000) - 60_000

        peak = entry * (1.0 + LONG1_ADVERSE_PCT / 100.0 + 0.001)
        sc.on_tick(sym, peak)
        assert coin.long1 is not None, "long1 should open at +2% against the short"
        coin.long1.tp_price = None  # isolate the peak-retrace rule from the long TP

        sc.on_tick(sym, peak * 1.004)  # new peak
        sc.on_tick(sym, peak * 1.004 * (1.0 - (LONG_HEDGE_PULLBACK_PCT + 0.05) / 100.0))
        assert coin.long1 is None, "long1 must close on a 0.5% retrace from its peak"
        assert coin.short is not None, "closing long1 must not touch the primary short"
    print("OK long1: opens at +2%, closes on 0.5% peak retrace")


def test_long2_closes_immediately_on_half_pct_retrace() -> None:
    with _no_smart_exit():
        conn = FakeConnector()
        sc = MomentumScanner(conn, lambda: True)
        sym = "TESTUSDT"
        entry = 100.0
        sc.load_symbols([sym])
        sc.on_tick(sym, entry)
        coin = sc._coins[sym]
        from momentum_scanner import LegPosition, LONG2_LEVERAGE, MAGIC_LONG2, MAGIC_SHORT, SHORT_LEVERAGE

        peak = entry * 1.05
        coin.short = LegPosition("SELL", entry, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
        coin.short_trough_price = entry
        coin.long2 = LegPosition("BUY", entry * 1.04, 1.0, LONG2_LEVERAGE, MAGIC_LONG2, None)
        coin.long2_peak_price = peak
        coin.status = STATUS_LONG2
        coin.long2_was_closed = False
        sc.on_tick(sym, peak * (1.0 - (LONG_HEDGE_PULLBACK_PCT + 0.05) / 100.0))
        assert coin.long2 is None, "long2 must close on a 0.5% retrace from its peak"
        assert coin.short is not None
    print("OK long2: closes immediately on 0.5% peak retrace")


def test_short_survives_sub_1pct_adverse() -> None:
    """Regression: the short must not be stopped out before Long1 can arm."""
    with _no_smart_exit():
        conn = FakeConnector()
        sc = MomentumScanner(conn, lambda: True)
        sym = "TESTUSDT"
        entry = 100.0
        sc.load_symbols([sym])
        sc.on_tick(sym, entry)
        coin = sc._coins[sym]
        from momentum_scanner import LegPosition, MAGIC_SHORT, SHORT_LEVERAGE

        coin.short = LegPosition("SELL", entry, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
        coin.short_trough_price = entry
        coin.status = STATUS_SHORT
        coin.short_opened_ms = int(time.time() * 1000) - 60_000
        sc.on_tick(sym, entry * 1.006)  # +0.6% against the short
        assert coin.short is not None, "short must survive sub-1% adverse (recovery path)"
        sc.on_tick(sym, entry * (1.0 + LONG1_ADVERSE_PCT / 100.0 + 0.001))
        assert coin.long1 is not None, "long1 must arm at +2%"
    print("OK short survives sub-1% adverse before long1")


def test_naked_short_trail_waits_for_recovery() -> None:
    """Do not trail-scratch a naked short before Long1/Long2 can still arm."""
    with _no_smart_exit():
        conn = FakeConnector()
        sc = MomentumScanner(conn, lambda: True)
        sym = "TESTUSDT"
        entry = 100.0
        sc.load_symbols([sym])
        sc.on_tick(sym, entry)
        coin = sc._coins[sym]
        from momentum_scanner import LegPosition, MAGIC_SHORT, SHORT_LEVERAGE

        coin.short = LegPosition("SELL", entry, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
        coin.short_trough_price = entry * 0.98  # -2% MFE
        coin.status = STATUS_SHORT
        coin.short_opened_ms = int(time.time() * 1000) - 60_000
        # Bounce 1.6% off the trough but still below entry — old logic scratched here.
        sc.on_tick(sym, entry * 0.997)
        assert coin.short is not None, "naked short must stay open for the recovery window"
        assert coin.long1 is None
    print("OK naked short trail waits for Long1 window")


def test_short_trail_closes_after_recovery_cycle() -> None:
    with _no_smart_exit():
        conn = FakeConnector()
        sc = MomentumScanner(conn, lambda: True)
        sc._partition_usd = 100.0
        sym = "TESTUSDT"
        entry = 100.0
        sc.load_symbols([sym])
        sc.on_tick(sym, entry)
        coin = sc._coins[sym]
        from momentum_scanner import LegPosition, MAGIC_SHORT, SHORT_LEVERAGE

        coin.short = LegPosition("SELL", entry, 2.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
        coin.short_trough_price = entry * 0.94
        coin.status = STATUS_SHORT
        coin.short_opened_ms = int(time.time() * 1000) - 120_000
        # Recovery cycle finished — the trail is free to harvest the short profit.
        coin.long1_was_closed = True
        coin.long2_was_closed = True
        trough = entry * 0.94
        sc.on_tick(sym, trough * (1.0 + (SHORT_TRAIL_PULLBACK_PCT + 0.1) / 100.0))
        assert coin.short is None, "short may trail off once the recovery cycle is done"
    print("OK short trail harvests after the recovery cycle")


def test_long2_opens_after_long1_closed() -> None:
    """Continued pump to +4% must still arm Long2 after Long1 already closed."""
    with _no_smart_exit():
        conn = FakeConnector()
        sc = MomentumScanner(conn, lambda: True)
        sym = "TESTUSDT"
        entry = 100.0
        sc.load_symbols([sym])
        sc.on_tick(sym, entry)
        coin = sc._coins[sym]
        from momentum_scanner import LegPosition, MAGIC_SHORT, SHORT_LEVERAGE

        coin.short = LegPosition("SELL", entry, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
        coin.short_trough_price = entry
        coin.status = STATUS_SHORT
        coin.short_opened_ms = int(time.time() * 1000) - 120_000
        coin.long1 = None
        coin.long1_was_closed = True
        sc.on_tick(sym, entry * (1.0 + LONG2_ADVERSE_PCT / 100.0 + 0.001))
        assert coin.long2 is not None, "long2 should open at +4% even after long1 closed"
    print("OK long2: opens after long1 already closed")


def test_long2_opens_at_4pct_from_short() -> None:
    with _no_smart_exit():
        conn = FakeConnector()
        sc = MomentumScanner(conn, lambda: True)
        sym = "TESTUSDT"
        entry = 100.0
        sc.load_symbols([sym])
        sc.on_tick(sym, entry)
        coin = sc._coins[sym]
        from momentum_scanner import LegPosition, LONG1_LEVERAGE, MAGIC_LONG1, MAGIC_SHORT, SHORT_LEVERAGE

        l1_entry = entry * (1.0 + LONG1_ADVERSE_PCT / 100.0 + 0.001)
        coin.short = LegPosition("SELL", entry, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
        coin.short_trough_price = entry
        coin.long1 = LegPosition("BUY", l1_entry, 1.0, LONG1_LEVERAGE, MAGIC_LONG1, None)
        # Peak already above the Long2 trigger so the 0.5% trail does not fire first.
        coin.long1_peak_price = entry * (1.0 + LONG2_ADVERSE_PCT / 100.0 + 0.001)
        coin.status = STATUS_LONG1
        coin.short_opened_ms = int(time.time() * 1000) - 120_000
        coin.long1_opened_ms = int(time.time() * 1000) - 60_000

        sc.on_tick(sym, entry * (1.0 + LONG2_ADVERSE_PCT / 100.0 + 0.001))
        assert coin.long2 is not None, "long2 should open at +4% from the short entry"
    print("OK long2: opens at +4% from short entry")


def test_long1_blocked_without_short() -> None:
    sc = MomentumScanner(FakeConnector(), lambda: True)
    sym = "TESTUSDT"
    sc.load_symbols([sym])
    sc.on_tick(sym, 100.0)
    coin = sc._coins[sym]
    sc.on_tick(sym, 103.0)
    assert coin.long1 is None, "long1 must not open without an active short"
    print("OK long1 blocked without short")


def test_pair_flattens_when_short_removed() -> None:
    conn = FakeConnector()
    sc = MomentumScanner(conn, lambda: True)
    sym = "TESTUSDT"
    entry = 100.0
    sc.load_symbols([sym])
    sc.on_tick(sym, entry)
    coin = sc._coins[sym]
    from momentum_scanner import (
        LegPosition,
        LONG2_LEVERAGE,
        MAGIC_LONG2,
        MAGIC_SHORT,
        SHORT_LEVERAGE,
        STATUS_CLOSED,
    )

    coin.short = LegPosition("SELL", entry, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
    coin.long2 = LegPosition("BUY", entry, 0.5, LONG2_LEVERAGE, MAGIC_LONG2, None)
    coin.status = STATUS_LONG2
    coin.short = None
    sc._manage_positions(coin)
    assert coin.long2 is None, "long2 must close when the short is gone"
    assert coin.status == STATUS_CLOSED
    print("OK pair flattens when short removed")


def test_long1_requires_live_adverse_not_peak_only() -> None:
    with _no_smart_exit():
        conn = FakeConnector()
        sc = MomentumScanner(conn, lambda: True)
        sym = "TESTUSDT"
        entry = 100.0
        sc.load_symbols([sym])
        sc.on_tick(sym, entry)
        coin = sc._coins[sym]
        from momentum_scanner import LegPosition, MAGIC_SHORT, SHORT_LEVERAGE

        coin.short = LegPosition("SELL", entry, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
        coin.short_trough_price = entry
        coin.status = STATUS_SHORT
        coin.short_opened_ms = int(time.time() * 1000) - 60_000
        coin.short_adverse_peak_pct = LONG1_ADVERSE_PCT + 0.1
        sc.on_tick(sym, entry * 1.015)  # only +1.5% live
        assert coin.long1 is None, "long1 must not open on a peak latch after a fade"
        sc.on_tick(sym, entry * (1.0 + LONG1_ADVERSE_PCT / 100.0 + 0.001))
        assert coin.long1 is not None, "long1 opens when live adverse >= 2%"
    print("OK long1: requires live adverse, not peak-only")


def test_smart_exit_closes_full_pair() -> None:
    conn = FakeConnector()
    sc = MomentumScanner(conn, lambda: True)
    sc._partition_usd = 100.0
    sym = "TESTUSDT"
    entry = 100.0
    sc.load_symbols([sym])
    sc.on_tick(sym, entry)
    coin = sc._coins[sym]
    from momentum_scanner import LegPosition, MAGIC_SHORT, SHORT_LEVERAGE

    # qty sized so -2.8% clears 6% of partition + cost buffer (~$6.8)
    coin.short = LegPosition("SELL", entry, 3.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
    coin.short_trough_price = entry
    coin.status = STATUS_SHORT
    # Recovery cycle finished — smart exit may harvest; a naked pre-Long1 short must not.
    coin.long1_was_closed = True
    coin.long2_was_closed = True
    sc.on_tick(sym, entry * 0.972)
    assert coin.short is None, "smart exit should flatten when net clears TP economics"
    print("OK smart exit: closes full pair at meaningful net target")


def test_close_leg_failure_keeps_state() -> None:
    class FailCloseConnector(FakeConnector):
        def close_leg(self, sym, magic, qty) -> dict:
            return {"ok": False, "error": "simulated_fail"}

    conn = FailCloseConnector()
    sc = MomentumScanner(conn, lambda: True)
    sym = "TESTUSDT"
    entry = 100.0
    sc.load_symbols([sym])
    sc.on_tick(sym, entry)
    coin = sc._coins[sym]
    from momentum_scanner import LegPosition, LONG1_LEVERAGE, LONG_TP_PCT, MAGIC_LONG1, MAGIC_SHORT, SHORT_LEVERAGE

    tp = entry * (1.0 + LONG_TP_PCT / 100.0)
    coin.short = LegPosition("SELL", 98.0, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
    coin.short_trough_price = 98.0
    coin.long1 = LegPosition("BUY", entry, 1.0, LONG1_LEVERAGE, MAGIC_LONG1, tp)
    coin.long1_peak_price = entry
    coin.status = STATUS_LONG1
    sc.on_tick(sym, tp + 0.01)
    assert coin.long1 is not None, "failed close must not clear in-memory leg"
    print("OK close leg failure preserves state")


def test_long1_blocked_until_short_active() -> None:
    with _no_smart_exit():
        conn = FakeConnector()
        sc = MomentumScanner(conn, lambda: True)
        sym = "TESTUSDT"
        entry = 100.0
        sc.load_symbols([sym])
        sc.on_tick(sym, entry)
        coin = sc._coins[sym]
        coin.short_was_closed = True
        coin.short_adverse_peak_pct = LONG2_ADVERSE_PCT + 0.1
        sc.on_tick(sym, entry * (1.0 + LONG2_ADVERSE_PCT / 100.0 + 0.001))
        assert coin.long1 is None, "long1 must not open without an active short"
    print("OK long1 blocked until short is open")


def test_long2_does_not_reenter_after_close() -> None:
    with _no_smart_exit():
        conn = FakeConnector()
        sc = MomentumScanner(conn, lambda: True)
        sym = "TESTUSDT"
        entry = 100.0
        sc.load_symbols([sym])
        sc.on_tick(sym, entry)
        coin = sc._coins[sym]
        from momentum_scanner import LegPosition, LONG1_LEVERAGE, MAGIC_LONG1, MAGIC_SHORT, SHORT_LEVERAGE

        coin.short = LegPosition("SELL", entry, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
        coin.short_trough_price = entry
        coin.long1 = LegPosition("BUY", 102.0, 1.0, LONG1_LEVERAGE, MAGIC_LONG1, None)
        coin.long1_peak_price = entry * (1.0 + LONG2_ADVERSE_PCT / 100.0 + 0.001)
        coin.status = STATUS_LONG1
        coin.short_opened_ms = int(time.time() * 1000) - 120_000
        coin.long1_opened_ms = int(time.time() * 1000) - 60_000
        sc.on_tick(sym, entry * (1.0 + LONG2_ADVERSE_PCT / 100.0 + 0.001))
        assert coin.long2 is not None
        coin.long2 = None
        coin.long2_was_closed = True
        sc.on_tick(sym, entry * (1.0 + LONG2_ADVERSE_PCT / 100.0 + 0.01))
        assert coin.long2 is None, "long2 must be one-shot for the pair lifetime"
    print("OK long2: no re-entry after close")


def test_gap_to_4pct_opens_long1_then_long2() -> None:
    with _no_smart_exit():
        conn = FakeConnector()
        sc = MomentumScanner(conn, lambda: True)
        sym = "TESTUSDT"
        entry = 100.0
        sc.load_symbols([sym])
        sc.on_tick(sym, entry)
        coin = sc._coins[sym]
        from momentum_scanner import LegPosition, MAGIC_SHORT, SHORT_LEVERAGE

        coin.short = LegPosition("SELL", entry, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
        coin.short_trough_price = entry
        coin.status = STATUS_SHORT
        coin.short_opened_ms = int(time.time() * 1000) - 60_000
        gap_price = entry * (1.0 + LONG2_ADVERSE_PCT / 100.0 + 0.001)
        sc.on_tick(sym, gap_price)
        assert coin.long1 is not None, "gap up must open long1"
        assert coin.long2 is not None, "gap up must open long2 at +4% from the short"
    print("OK gap up: long1 then long2")


def test_settle_delay_blocks_long1() -> None:
    with _no_smart_exit():
        with unittest.mock.patch.object(momentum_scanner_mod, "LONG_ENTRY_DELAY_MS", 3000):
            conn = FakeConnector()
            sc = MomentumScanner(conn, lambda: True)
            sym = "TESTUSDT"
            entry = 100.0
            sc.load_symbols([sym])
            sc.on_tick(sym, entry)
            coin = sc._coins[sym]
            from momentum_scanner import LegPosition, MAGIC_SHORT, SHORT_LEVERAGE

            coin.short = LegPosition("SELL", entry, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
            coin.short_trough_price = entry
            coin.status = STATUS_SHORT
            coin.short_opened_ms = int(time.time() * 1000)
            sc.on_tick(sym, entry * (1.0 + LONG1_ADVERSE_PCT / 100.0 + 0.001))
            assert coin.long1 is None, "long1 must wait for the settle delay"
            coin.short_opened_ms = 0
            sc.on_tick(sym, entry * (1.0 + LONG1_ADVERSE_PCT / 100.0 + 0.002))
            assert coin.long1 is None, "long1 blocked when the settle clock is missing"
    print("OK settle delay blocks long1")


def test_pending_keeps_latched_15m_during_retrace() -> None:
    prev = os.environ.get("SCANNER_EXEC")
    os.environ["SCANNER_EXEC"] = "0"
    try:
        sc = MomentumScanner(FakeConnector(), lambda: True)
        sym = "TESTUSDT"
        base = 100.0
        _seed_base(sc, sym, base)
        spike = base * 1.055
        sc.on_tick(sym, spike)
        coin = sc._coins[sym]
        assert coin.status == STATUS_WATCHING
        retrace_price = spike * (1.0 - 0.008)
        sc.on_tick(sym, retrace_price)
        assert coin.status == STATUS_PENDING, "pending must hold while latched gain qualifies"
        sc.on_tick(sym, spike * 1.01)
        assert coin.retrace_pct < RETRACE_ENTRY_PCT
        assert coin.status == STATUS_WATCHING
        print("OK pending uses latched 15m qualify through retrace")
    finally:
        if prev is None:
            os.environ.pop("SCANNER_EXEC", None)
        else:
            os.environ["SCANNER_EXEC"] = prev


def test_pending_entry_not_resent_on_every_tick() -> None:
    class CountingConnector(FakeConnector):
        def __init__(self) -> None:
            super().__init__()
            self.exec_calls = 0

        def place_market_order(self, symbol, side, quantity, **kwargs) -> dict:
            self.exec_calls += 1
            return super().place_market_order(symbol, side, quantity, **kwargs)

    conn = CountingConnector()
    sc = MomentumScanner(conn, lambda: True)
    sym = "ACEUSDT"
    sc.load_symbols([sym])
    coin = sc._coins[sym]
    coin.status = STATUS_PENDING
    coin.price = 0.1229
    coin.best_pct = 6.0
    coin.qualifying_pct = 6.0
    coin.pct_15m = 6.0
    coin.retrace_pct = 0.8
    coin.highest_price = 0.125
    coin.entry_signal_key = "ACEUSDT_1250_600"
    for _ in range(5):
        sc._try_open_short_entry(coin)
    assert conn.exec_calls == 1, f"expected one exchange order, got {conn.exec_calls}"
    assert coin.submitted_entry_signal_id, "entry signal should be marked submitted"
    print("OK pending entry fires once per signal")


def test_stale_pending_demoted_when_live_15m_collapses() -> None:
    prev = os.environ.get("SCANNER_EXEC")
    os.environ["SCANNER_EXEC"] = "0"
    try:
        sc = MomentumScanner(FakeConnector(), lambda: True)
        sym = "STALEUSDT"
        base = 100.0
        _seed_base(sc, sym, base)
        spike = base * 1.055
        sc.on_tick(sym, spike)
        coin = sc._coins[sym]
        retrace_price = spike * (1.0 - 0.008)
        sc.on_tick(sym, retrace_price)
        assert coin.status == STATUS_PENDING
        coin.pct_15m = -8.0
        coin.retrace_pct = 18.0
        sc._demote_stale_pending(coin)
        assert coin.status == STATUS_WATCHING
        assert coin.qualifying_pct == 0.0
        print("OK stale pending demoted when live 15m dead / retrace exhausted")
    finally:
        if prev is None:
            os.environ.pop("SCANNER_EXEC", None)
        else:
            os.environ["SCANNER_EXEC"] = prev


def test_short_tp_with_longs_flattens_full_pair() -> None:
    """Closing the primary short while Long1/Long2 are open must not orphan the longs."""
    with _no_smart_exit():
        conn = FakeConnector()
        sc = MomentumScanner(conn, lambda: True)
        sym = "TESTUSDT"
        entry = 100.0
        sc.load_symbols([sym])
        sc.on_tick(sym, entry)
        coin = sc._coins[sym]
        from momentum_scanner import (
            LegPosition,
            LONG1_LEVERAGE,
            LONG2_LEVERAGE,
            MAGIC_LONG1,
            MAGIC_LONG2,
            MAGIC_SHORT,
            SHORT_LEVERAGE,
            SHORT_TP_PCT,
            STATUS_CLOSED,
        )

        tp = entry * (1.0 - SHORT_TP_PCT / 100.0)
        coin.short = LegPosition("SELL", entry, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, tp)
        coin.short_trough_price = entry
        coin.long1 = LegPosition("BUY", entry * 1.02, 0.4, LONG1_LEVERAGE, MAGIC_LONG1, None)
        coin.long2 = LegPosition("BUY", entry * 1.04, 0.4, LONG2_LEVERAGE, MAGIC_LONG2, None)
        coin.long1_peak_price = entry * 1.02
        coin.long2_peak_price = entry * 1.04
        coin.status = STATUS_LONG2
        sc.on_tick(sym, tp - 0.01)
        assert coin.short is None and coin.long1 is None and coin.long2 is None
        assert coin.status == STATUS_CLOSED
    print("OK short TP with longs flattens full pair")


def test_failed_entry_keeps_sticky_submit() -> None:
    """Failed order must not immediately clear submitted id (prevents retry storms)."""

    class FailOnceConnector(FakeConnector):
        def place_market_order(self, symbol, side, quantity, **kwargs) -> dict:
            self.orders.append({"sym": symbol, "side": side, "qty": quantity})
            return {"ok": False, "error": "timeout", "retryable": True}

    conn = FailOnceConnector()
    sc = MomentumScanner(conn, lambda: True)
    sym = "STICKYUSDT"
    sc.load_symbols([sym])
    coin = sc._coins[sym]
    coin.status = STATUS_PENDING
    coin.price = 1.0
    coin.best_pct = 6.0
    coin.qualifying_pct = 6.0
    coin.pct_15m = 6.0
    coin.retrace_pct = 0.8
    coin.highest_price = 1.02
    coin.entry_signal_key = "STICKYUSDT_10200_600"
    sc._try_open_short_entry(coin)
    assert coin.submitted_entry_signal_id, "submit id must stick after failure"
    assert coin.entry_submit_ms > 0
    n = len(conn.orders)
    sc._try_open_short_entry(coin)
    assert len(conn.orders) == n, "sticky submit must block immediate re-send"
    print("OK failed entry keeps sticky submit")


def test_adopt_is_noop_in_paper_mode() -> None:
    """Restart adoption is a live-exchange recovery — paper scanning must be untouched."""
    conn = FakeConnector()
    sc = MomentumScanner(conn, lambda: True)
    sym = "TESTUSDT"
    sc.load_symbols([sym])
    out = sc.adopt_open_strategies_from_exchange()
    assert out == {"adopted_shorts": 0, "adopted_longs": 0, "symbols": []}
    sc.on_tick(sym, 100.0)
    assert sc._coins[sym].short is None
    print("OK adopt is a no-op in paper mode")


def test_primary_entry_is_sell_short_leg() -> None:
    conn = FakeConnector()
    sc = MomentumScanner(conn, lambda: True)
    sym = "SIDEUSDT"
    sc.load_symbols([sym])
    coin = sc._coins[sym]
    coin.status = STATUS_PENDING
    coin.price = 2.0
    coin.best_pct = 6.0
    coin.qualifying_pct = 6.0
    coin.pct_15m = 6.0
    coin.retrace_pct = 0.8
    coin.highest_price = 2.05
    coin.entry_signal_key = "SIDEUSDT_20500_600"
    sc._try_open_short_entry(coin)
    assert coin.short is not None and coin.short.side == "SELL"
    assert coin.status == STATUS_SHORT
    assert conn.orders and conn.orders[0]["side"] == "SELL"
    assert conn.orders[0].get("leg") == "SHORT"
    print("OK primary entry is a SELL SHORT leg")


if __name__ == "__main__":
    try:
        test_multi_tf_gain_then_retrace_pending()
        test_short_tp_at_2_5_pct()
        test_long2_tp_at_2_5_pct()
        test_long1_opens_at_2pct_and_closes_on_half_pct_retrace()
        test_long2_closes_immediately_on_half_pct_retrace()
        test_short_survives_sub_1pct_adverse()
        test_naked_short_trail_waits_for_recovery()
        test_short_trail_closes_after_recovery_cycle()
        test_long2_opens_after_long1_closed()
        test_long2_opens_at_4pct_from_short()
        test_long1_blocked_without_short()
        test_pair_flattens_when_short_removed()
        test_long1_requires_live_adverse_not_peak_only()
        test_smart_exit_closes_full_pair()
        test_close_leg_failure_keeps_state()
        test_long1_blocked_until_short_active()
        test_long2_does_not_reenter_after_close()
        test_gap_to_4pct_opens_long1_then_long2()
        test_settle_delay_blocks_long1()
        test_pending_entry_not_resent_on_every_tick()
        test_pending_keeps_latched_15m_during_retrace()
        test_stale_pending_demoted_when_live_15m_collapses()
        test_short_tp_with_longs_flattens_full_pair()
        test_failed_entry_keeps_sticky_submit()
        test_adopt_is_noop_in_paper_mode()
        test_primary_entry_is_sell_short_leg()
    except AssertionError as e:
        print("FAIL", e, file=sys.stderr)
        raise SystemExit(1)
