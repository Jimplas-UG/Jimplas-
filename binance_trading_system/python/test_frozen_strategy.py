#!/usr/bin/env python3
"""Regression lock: frozen long-first contract must not drift."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))


def test_frozen_contract_matches_live_modules() -> None:
    from frozen_strategy import STRATEGY_ID, assert_frozen_contract, frozen_contract_snapshot

    snap = assert_frozen_contract()
    assert snap["strategy_id"] == STRATEGY_ID
    assert snap["primary"]["side"] == "BUY"
    assert snap["recovery"]["side"] == "SELL"
    assert snap["primary"]["partition_pct"] == 50.0
    assert snap["recovery"]["partition_pct"] == 12.5
    print("OK frozen contract matches live modules")


def test_forbidden_short_first_labels_rejected() -> None:
    from frozen_strategy import FORBIDDEN_STATUSES
    import momentum_scanner as ms

    live = {ms.STATUS_SHORT, ms.STATUS_LONG1, ms.STATUS_LONG2}
    assert live.isdisjoint(FORBIDDEN_STATUSES)
    assert ms.STATUS_LONG1 == "Long"
    assert ms.STATUS_SHORT == "Short 1"
    assert ms.STATUS_LONG2 == "Short 2"
    print("OK long-first status labels in use")


def test_execution_engine_allows_primary_long() -> None:
    from execution_engine import ExecutionEngine, ExecutionSignal

    class _C:
        cfg = type("cfg", (), {"paper": True, "api_key": "x"})()

        def ensure_hedge_mode(self):
            return True, ""

    eng = ExecutionEngine(_C(), open_trade_count=lambda: 0)
    # Standalone BUY without primary/manual leg must block.
    bad = ExecutionSignal(
        symbol="TAGUSDT",
        side="BUY",
        quantity=1.0,
        reference_price=1.0,
        leverage=5,
        magic=1,
        leg="SHORT",
        signal_id="t1",
        signal_ts_ms=1,
    )
    assert eng._validate_short_first(bad) == "buy_blocked_short_first_policy"
    ok = ExecutionSignal(
        symbol="TAGUSDT",
        side="BUY",
        quantity=1.0,
        reference_price=1.0,
        leverage=5,
        magic=88002,
        leg="LONG1",
        signal_id="t2",
        signal_ts_ms=1,
    )
    assert eng._validate_short_first(ok) is None
    print("OK execution engine allows primary long")


def test_scanner_status_exposes_strategy_id() -> None:
    from momentum_scanner import MomentumScanner

    class _C:
        cfg = type("cfg", (), {"paper": True, "api_key": ""})()

        def positions(self, *a, **k):
            return []

    sc = MomentumScanner(_C(), get_testnet=lambda: False)
    st = sc.status()
    assert st.get("strategy_id") == "long_first_v1"
    assert "Short 1" in str(st.get("strategy_name") or "")
    print("OK scanner status exposes frozen strategy id")


def test_snapshot_unchanged() -> None:
    from frozen_strategy import frozen_contract_snapshot

    a = frozen_contract_snapshot()
    b = frozen_contract_snapshot()
    assert a == b
    print("OK frozen snapshot is stable")


if __name__ == "__main__":
    test_frozen_contract_matches_live_modules()
    test_forbidden_short_first_labels_rejected()
    test_execution_engine_allows_primary_long()
    test_scanner_status_exposes_strategy_id()
    test_snapshot_unchanged()
    print("test_frozen_strategy: ALL OK")
