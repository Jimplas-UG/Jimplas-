#!/usr/bin/env python3
"""One-pair isolation gate tests."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from pair_isolation import PairIsolationGate  # noqa: E402


def test_blocks_second_symbol() -> None:
    gate = PairIsolationGate()
    scanner_active = lambda: "BTCUSDT"
    exchange = lambda: []
    ok, reason = gate.can_open("ETHUSDT", scanner_active, exchange)
    assert not ok
    assert "one_pair_active" in reason


def test_allows_same_symbol_legs() -> None:
    gate = PairIsolationGate()
    scanner_active = lambda: "BTCUSDT"
    exchange = lambda: []
    ok, _ = gate.can_open("BTCUSDT", scanner_active, exchange)
    assert ok


def test_close_pending_blocks() -> None:
    gate = PairIsolationGate()
    gate.begin_close("BTCUSDT")
    ok, reason = gate.can_open("BTCUSDT", lambda: None, lambda: [])
    assert not ok
    assert reason == "close_pending"
    gate.end_close("BTCUSDT")
    ok, _ = gate.can_open("BTCUSDT", lambda: None, lambda: [])
    assert ok


def test_exchange_position_blocks() -> None:
    gate = PairIsolationGate()
    exchange = lambda: [{"symbol": "SOLUSDT", "volume": 0.5}]
    ok, reason = gate.can_open("ETHUSDT", lambda: None, exchange)
    assert not ok
    assert "SOLUSDT" in reason


def test_nested_close_refcount() -> None:
    gate = PairIsolationGate()
    gate.begin_close("BTCUSDT")
    gate.begin_close("BTCUSDT")  # nested (api + leg)
    gate.end_close("BTCUSDT")
    assert gate.is_close_pending("BTCUSDT"), "inner end must not clear outer close"
    gate.end_close("BTCUSDT")
    assert not gate.is_close_pending("BTCUSDT")


def test_close_all_blocks_opens() -> None:
    gate = PairIsolationGate()
    gate.begin_close_all(["BTCUSDT"])
    ok, reason = gate.can_open("ETHUSDT", lambda: None, lambda: [])
    assert not ok and reason == "close_all_pending"
    gate.end_close_all(["BTCUSDT"])
    ok, _ = gate.can_open("ETHUSDT", lambda: None, lambda: [])
    assert ok


def test_stale_close_all_releases_when_flat() -> None:
    import time as _t

    from pair_isolation import CLOSE_GATE_FLAT_RELEASE_MS

    gate = PairIsolationGate()
    gate.begin_close_all(["AKEUSDT"])
    # Simulate a gate that has been stuck longer than the flat-release window.
    gate._global_close_all_ms = int(_t.time() * 1000) - (CLOSE_GATE_FLAT_RELEASE_MS + 1000)
    gate._close_started_ms["AKEUSDT"] = gate._global_close_all_ms
    released = gate.release_stale_close_gates(lambda: [])
    assert released.get("cleared_close_all") is True
    ok, _ = gate.can_open("ETHUSDT", lambda: None, lambda: [])
    assert ok
    print("OK stale close_all releases when flat")


def test_force_clear_close_gates() -> None:
    gate = PairIsolationGate()
    gate.begin_close_all(["X"])
    gate.begin_close("YUSDT")
    out = gate.force_clear_close_gates("test")
    assert out["cleared_close_all"] is True
    assert not gate.is_close_pending("YUSDT")
    ok, _ = gate.can_open("ETHUSDT", lambda: None, lambda: [])
    assert ok


def main() -> int:
    tests = [
        test_blocks_second_symbol,
        test_allows_same_symbol_legs,
        test_close_pending_blocks,
        test_exchange_position_blocks,
        test_nested_close_refcount,
        test_close_all_blocks_opens,
        test_stale_close_all_releases_when_flat,
        test_force_clear_close_gates,
    ]
    failed = 0
    for t in tests:
        try:
            t()
            print("OK", t.__name__)
        except Exception as e:
            failed += 1
            print("FAIL", t.__name__, e)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
