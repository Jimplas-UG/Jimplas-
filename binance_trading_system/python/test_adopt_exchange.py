#!/usr/bin/env python3
"""Restart-recovery tests: scanner must adopt live exchange positions it has forgotten."""
from __future__ import annotations

import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))

os.environ.setdefault("SCANNER_LONG_DELAY_MS", "0")
os.environ.setdefault("SCANNER_EXEC", "0")

from momentum_scanner import (  # noqa: E402
    LONG1_ADVERSE_PCT,
    SHORT_TP_PCT,
    STATUS_LONG1,
    STATUS_SCANNING,
    STATUS_SHORT,
    MomentumScanner,
)


class LiveConnector:
    """Minimal live-mode connector holding one hedge pair on the exchange."""

    def __init__(self, positions: list[dict] | None = None) -> None:
        self.cfg = SimpleNamespace(paper=False, api_key="k", api_secret="s", symbol="RIFUSDT")
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

    def close_by_position_side(self, symbol, position_side, volume=None) -> dict:
        self.closed.append({"symbol": symbol, "position_side": position_side})
        return {"ok": True}

    def status_snapshot(self, **_k) -> dict:
        return {"connected": True}


def _short_pos(symbol="RIFUSDT", entry=0.05, qty=1000.0) -> dict:
    return {
        "symbol": symbol,
        "type": "SELL",
        "positionSide": "SHORT",
        "volume": qty,
        "price_open": entry,
    }


def _long_pos(symbol="RIFUSDT", entry=0.051, qty=800.0) -> dict:
    return {
        "symbol": symbol,
        "type": "BUY",
        "positionSide": "LONG",
        "volume": qty,
        "price_open": entry,
    }


def test_adopt_short_from_empty_scanner() -> None:
    """RIFUSDT case: exchange holds a SHORT, scanner remembers nothing."""
    conn = LiveConnector([_short_pos()])
    sc = MomentumScanner(conn, lambda: False)
    sc.load_symbols(["RIFUSDT"])
    coin = sc._coins["RIFUSDT"]
    assert coin.status == STATUS_SCANNING and coin.short is None

    out = sc.adopt_open_strategies_from_exchange()
    assert out["adopted_shorts"] == 1, out
    assert out["symbols"] == ["RIFUSDT"], out
    assert coin.short is not None and coin.short.side == "SELL"
    assert coin.status == STATUS_SHORT
    assert abs(coin.short.tp_price - 0.05 * (1 - SHORT_TP_PCT / 100.0)) < 1e-12
    assert coin.short.qty == 1000.0
    assert sc._global_active_symbol() == "RIFUSDT"
    print("OK adopt: exchange short -> scanner Short status")


def test_adopted_short_is_managed_and_arms_long1() -> None:
    """After adopt, _manage_positions must run — Long 1 arms at +2% adverse."""
    conn = LiveConnector([_short_pos()])
    sc = MomentumScanner(conn, lambda: False)
    sc.load_symbols(["RIFUSDT"])
    sc.adopt_open_strategies_from_exchange()
    coin = sc._coins["RIFUSDT"]
    coin.short_opened_ms = int(time.time() * 1000) - 60_000
    assert sc._long1_entry_allowed(coin) is False, "flat price must not arm Long 1"
    coin.price = 0.05 * (1.0 + LONG1_ADVERSE_PCT / 100.0 + 0.001)
    assert sc._long1_entry_allowed(coin) is True, "adopted short must be eligible for Long 1"
    print("OK adopt: adopted short is manage-eligible (Long 1 arms)")


def test_adopt_short_and_long_pair() -> None:
    conn = LiveConnector([_short_pos(), _long_pos()])
    sc = MomentumScanner(conn, lambda: False)
    out = sc.adopt_open_strategies_from_exchange()
    coin = sc._coins["RIFUSDT"]
    assert out["adopted_shorts"] == 1 and out["adopted_longs"] >= 1, out
    assert coin.short is not None and coin.long1 is not None
    assert coin.status in (STATUS_LONG1, "Long 2")
    print("OK adopt: short + long pair adopted short-first")


def test_adopt_skips_orphan_long_without_short() -> None:
    conn = LiveConnector([_long_pos()])
    sc = MomentumScanner(conn, lambda: False)
    out = sc.adopt_open_strategies_from_exchange()
    assert out["adopted_shorts"] == 0 and out["adopted_longs"] == 0, out
    assert "RIFUSDT" not in sc._coins or sc._coins["RIFUSDT"].long1 is None
    print("OK adopt: orphan long is never adopted")


def test_adopt_never_opens_new_trades() -> None:
    conn = LiveConnector([])
    sc = MomentumScanner(conn, lambda: False)
    sc.load_symbols(["RIFUSDT"])
    out = sc.adopt_open_strategies_from_exchange()
    assert out == {"adopted_shorts": 0, "adopted_longs": 0, "symbols": []}
    assert sc._coins["RIFUSDT"].short is None
    print("OK adopt: flat exchange adopts nothing")


def test_reconcile_adopts_short() -> None:
    conn = LiveConnector([_short_pos()])
    sc = MomentumScanner(conn, lambda: False)
    sc.load_symbols(["RIFUSDT"])
    r = sc.reconcile_from_exchange()
    coin = sc._coins["RIFUSDT"]
    assert coin.short is not None, "reconcile must adopt the live short"
    assert coin.status == STATUS_SHORT
    assert "RIFUSDT" not in r["reset_symbols"], r
    assert r["adopted"]["adopted_shorts"] == 1, r
    print("OK reconcile: adopts live short instead of leaving it unmanaged")


def test_tick_adopts_short_before_status_machine() -> None:
    conn = LiveConnector([_short_pos()])
    sc = MomentumScanner(conn, lambda: False)
    sc.load_symbols(["RIFUSDT"])
    sc.on_tick("RIFUSDT", 0.05)
    coin = sc._coins["RIFUSDT"]
    assert coin.short is not None, "tick must adopt a live short"
    assert coin.status == STATUS_SHORT
    print("OK tick: adopts live short on the next tick")


def test_adopted_short_manages_short_tp_on_tick() -> None:
    """Full RIFUSDT path: restart -> tick -> adopt -> SHORT_TP fires (no more dead pair)."""
    conn = LiveConnector([_short_pos()])
    sc = MomentumScanner(conn, lambda: False)
    sc.load_symbols(["RIFUSDT"])
    sc.on_tick("RIFUSDT", 0.05)
    coin = sc._coins["RIFUSDT"]
    assert coin.short is not None
    coin.long1_was_closed = True
    coin.long2_was_closed = True
    sc.on_tick("RIFUSDT", coin.short.tp_price - 1e-6)
    assert conn.closed, "SHORT_TP must reach the connector after adoption"
    assert coin.short is None
    print("OK adopt: SHORT_TP fires on a later tick for an adopted short")


def test_ensure_pair_coherence_adopts_instead_of_flattening() -> None:
    conn = LiveConnector([_short_pos()])
    sc = MomentumScanner(conn, lambda: False)
    sc.load_symbols(["RIFUSDT"])
    coin = sc._coins["RIFUSDT"]
    coin.price = 0.05
    assert sc._ensure_pair_coherence(coin) is True, "coherence must adopt, not bail out"
    assert coin.short is not None
    assert not conn.closed, "adoption must never flatten the live short"
    print("OK coherence: adopts a forgotten short instead of returning False")


def test_close_failure_backoff_blocks_retry_storm() -> None:
    class FailCloseConnector(LiveConnector):
        def __init__(self) -> None:
            super().__init__([_short_pos()])
            self.close_calls = 0

        def close_position(self, symbol=None, volume=None) -> dict:
            self.close_calls += 1
            return {"ok": False, "error": "partial_close_remaining_legs", "remaining": [{"x": 1}]}

    conn = FailCloseConnector()
    sc = MomentumScanner(conn, lambda: False)
    sc.load_symbols(["RIFUSDT"])
    sc.adopt_open_strategies_from_exchange()
    coin = sc._coins["RIFUSDT"]
    coin.price = 0.048

    r = sc._close_all(coin, "SHORT_TP")
    assert not r.get("ok")
    assert conn.close_calls == 1
    assert sc._close_backoff_active("RIFUSDT"), "failed close must arm a backoff"

    r2 = sc._close_all(coin, "SHORT_TP")
    assert r2.get("error") == "close_backoff", r2
    assert conn.close_calls == 1, "backoff must stop the per-tick close storm"
    assert coin.short is not None, "state is preserved while the close is retried later"

    # Manual close always bypasses the backoff.
    sc._close_all(coin, "MANUAL_PAIR", force=True)
    assert conn.close_calls == 2
    print("OK close backoff: failed close cannot spam every tick")


def test_close_backoff_grows_and_clears() -> None:
    conn = LiveConnector([_short_pos()])
    sc = MomentumScanner(conn, lambda: False)
    sc._note_close_failure("RIFUSDT")
    first = sc._close_fail_ms["RIFUSDT"]
    sc._note_close_failure("RIFUSDT")
    second = sc._close_fail_ms["RIFUSDT"]
    assert sc._close_fail_count["RIFUSDT"] == 2
    assert second - first > 0, "backoff must grow exponentially"
    for _ in range(12):
        sc._note_close_failure("RIFUSDT")
    capped = sc._close_fail_ms["RIFUSDT"] - int(time.time() * 1000)
    assert capped <= 30_000 + 50, f"backoff must cap at 30s, got {capped}"
    sc._clear_close_backoff("RIFUSDT")
    assert not sc._close_backoff_active("RIFUSDT")
    print("OK close backoff: exponential, capped at 30s, cleared on success")


def test_manage_still_arms_long1_during_close_backoff() -> None:
    conn = LiveConnector([_short_pos()])
    sc = MomentumScanner(conn, lambda: False)
    sc.load_symbols(["RIFUSDT"])
    sc.adopt_open_strategies_from_exchange()
    coin = sc._coins["RIFUSDT"]
    coin.short_opened_ms = int(time.time() * 1000) - 60_000
    coin.short.tp_price = 0.0499  # TP already hit — would close every tick
    sc._note_close_failure("RIFUSDT")

    opened: list[str] = []
    sc._try_open_long1 = lambda c: opened.append(c.symbol)  # type: ignore[method-assign]
    coin.price = 0.05 * (1.0 + LONG1_ADVERSE_PCT / 100.0 + 0.001)
    sc._manage_positions(coin)
    assert opened == ["RIFUSDT"], "Long 1 must still arm while the close backs off"
    assert coin.short is not None
    print("OK close backoff: Long 1 entry still runs")


def test_adopt_single_long_past_4pct_as_long2() -> None:
    """One-partition long with short already +4% adverse → Long 2, not a fake Long 1."""
    from momentum_scanner import LONG2_ADVERSE_PCT, STATUS_LONG2

    entry = 0.05
    price = entry * (1.0 + LONG2_ADVERSE_PCT / 100.0 + 0.001)
    conn = LiveConnector([_short_pos(entry=entry), _long_pos(entry=price, qty=800.0)])
    sc = MomentumScanner(conn, lambda: False)
    sc.load_symbols(["RIFUSDT"])
    coin = sc._coins["RIFUSDT"]
    coin.price = price
    out = sc.adopt_open_strategies_from_exchange()
    assert out["adopted_shorts"] == 1
    assert coin.long1 is None, "must not mis-label the residual as Long 1"
    assert coin.long1_was_closed is True
    assert coin.long2 is not None and coin.status == STATUS_LONG2
    print("OK adopt: +4% single long residual → Long 2")


def test_adopt_long1_qty_excludes_existing_long2() -> None:
    conn = LiveConnector(
        [_short_pos(), _long_pos(qty=1600.0)]  # combined long
    )
    sc = MomentumScanner(conn, lambda: False)
    sc.load_symbols(["RIFUSDT"])
    coin = sc._coins["RIFUSDT"]
    coin.price = 0.051
    # Pretend Long 2 already recovered in memory.
    from momentum_scanner import LegPosition, LONG2_LEVERAGE, MAGIC_LONG2

    coin.short = None
    sc.adopt_open_strategies_from_exchange()
    assert coin.short is not None
    # Force long2 present then re-adopt long1 attribution
    coin.long2 = LegPosition("BUY", 0.051, 800.0, LONG2_LEVERAGE, MAGIC_LONG2, 0.052)
    coin.long1 = None
    assert sc._adopt_exchange_long1(coin, "RIFUSDT", 1600.0, 0.051, 0.052)
    assert abs(coin.long1.qty - 800.0) < 1e-6, coin.long1.qty
    print("OK adopt: Long1 qty excludes existing Long2 share")


def test_sibling_wipe_marks_rearm_not_closed() -> None:
    """Closing Long1 must not permanently retire Long2 if the shared LONG was wiped."""
    from momentum_scanner import LegPosition, LONG1_LEVERAGE, LONG2_LEVERAGE, MAGIC_LONG1, MAGIC_LONG2

    class WipeConnector(LiveConnector):
        def close_by_position_side(self, symbol, position_side, volume=None) -> dict:
            # Simulate exchange wiping the whole LONG regardless of partial volume.
            self._positions = [p for p in self._positions if str(p.get("positionSide")) != "LONG"]
            return {"ok": True, "closed": [{"symbol": symbol, "position_side": position_side}]}

        def exchange_long_qty(self, symbol=None) -> float:
            return sum(
                float(p.get("volume") or 0)
                for p in self.positions(symbol)
                if str(p.get("positionSide") or "").upper() == "LONG"
            )

    conn = WipeConnector([_short_pos(), _long_pos(qty=1600.0)])
    sc = MomentumScanner(conn, lambda: False)
    sc.load_symbols(["RIFUSDT"])
    sc.adopt_open_strategies_from_exchange()
    coin = sc._coins["RIFUSDT"]
    coin.short_opened_ms = int(time.time() * 1000) - 60_000
    coin.long1 = LegPosition("BUY", 0.051, 800.0, LONG1_LEVERAGE, MAGIC_LONG1, 0.052)
    coin.long2 = LegPosition("BUY", 0.052, 800.0, LONG2_LEVERAGE, MAGIC_LONG2, 0.053)
    coin.long1_opened_ms = int(time.time() * 1000) - 60_000
    coin.long2_opened_ms = int(time.time() * 1000) - 60_000
    coin.price = 0.05 * 1.045

    reopened: list[str] = []
    sc._try_open_long2 = lambda c: reopened.append("long2")  # type: ignore[method-assign]
    sc._try_open_long1 = lambda c: reopened.append("long1")  # type: ignore[method-assign]
    sc._close_leg(coin, "long1", reason="LONG1_PULLBACK")
    assert coin.long2 is None
    assert coin.long2_was_closed is False
    assert coin.last_long2_exit_reason == "SIBLING_WIPE"
    assert "long2" in reopened, reopened
    print("OK close: sibling wipe re-arms Long2 instead of retiring it")


def test_close_vol_caps_to_preserve_sibling() -> None:
    from momentum_scanner import LegPosition, LONG1_LEVERAGE, LONG2_LEVERAGE, MAGIC_LONG1, MAGIC_LONG2

    class CapConnector(LiveConnector):
        def __init__(self) -> None:
            super().__init__([_short_pos(), _long_pos(qty=1600.0)])
            self.last_close_vol = None

        def close_by_position_side(self, symbol, position_side, volume=None) -> dict:
            self.last_close_vol = volume
            # Leave sibling residual on exchange.
            for p in self._positions:
                if str(p.get("positionSide")) == "LONG":
                    p["volume"] = 800.0
            return {"ok": True, "closed": [{"symbol": symbol}]}

        def exchange_long_qty(self, symbol=None) -> float:
            return 1600.0

    conn = CapConnector()
    sc = MomentumScanner(conn, lambda: False)
    sc.load_symbols(["RIFUSDT"])
    sc.adopt_open_strategies_from_exchange()
    coin = sc._coins["RIFUSDT"]
    # Inflated Long1 qty that would wipe sibling if uncapped.
    coin.long1 = LegPosition("BUY", 0.051, 1600.0, LONG1_LEVERAGE, MAGIC_LONG1, 0.052)
    coin.long2 = LegPosition("BUY", 0.052, 800.0, LONG2_LEVERAGE, MAGIC_LONG2, 0.053)
    sc._close_leg(coin, "long1", reason="LONG1_PULLBACK")
    assert conn.last_close_vol is not None
    assert conn.last_close_vol <= 800.0 + 1e-6, conn.last_close_vol
    assert coin.long2 is not None, "sibling must survive capped close"
    print("OK close: volume capped to preserve sibling long")


if __name__ == "__main__":
    try:
        test_adopt_short_from_empty_scanner()
        test_adopted_short_is_managed_and_arms_long1()
        test_adopt_short_and_long_pair()
        test_adopt_skips_orphan_long_without_short()
        test_adopt_never_opens_new_trades()
        test_reconcile_adopts_short()
        test_tick_adopts_short_before_status_machine()
        test_adopted_short_manages_short_tp_on_tick()
        test_ensure_pair_coherence_adopts_instead_of_flattening()
        test_close_failure_backoff_blocks_retry_storm()
        test_close_backoff_grows_and_clears()
        test_manage_still_arms_long1_during_close_backoff()
        test_adopt_single_long_past_4pct_as_long2()
        test_adopt_long1_qty_excludes_existing_long2()
        test_sibling_wipe_marks_rearm_not_closed()
        test_close_vol_caps_to_preserve_sibling()
    except AssertionError as e:
        print("FAIL", e, file=sys.stderr)
        raise SystemExit(1)
    print("test_adopt_exchange: ALL OK")
