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


def main() -> int:
    tests = [
        test_blocks_second_symbol,
        test_allows_same_symbol_legs,
        test_close_pending_blocks,
        test_exchange_position_blocks,
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
