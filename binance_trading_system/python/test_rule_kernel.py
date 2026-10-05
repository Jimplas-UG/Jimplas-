#!/usr/bin/env python3
"""Hard rule kernel — opens blocked; watchdog halt codes."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from rule_kernel import (
    LiveState,
    OpenIntent,
    audit_live_state,
    preflight_open,
    preflight_solo_hedge_exit,
    should_emergency_halt,
)


def test_blocks_early_long1() -> None:
    v = preflight_open(
        OpenIntent(
            symbol="AINUSDT",
            leg="LONG1",
            side="BUY",
            qty=1000,
            price=0.05,
            has_exchange_short=True,
            has_scanner_short=True,
            live_adverse_pct=0.64,
        )
    )
    assert not v.ok and v.code == "L1_EARLY", v
    print("OK kernel blocks early Long1")


def test_blocks_long1_past_inv() -> None:
    v = preflight_open(
        OpenIntent(
            symbol="X",
            leg="LONG1",
            side="BUY",
            qty=1,
            price=1,
            has_exchange_short=True,
            has_scanner_short=True,
            live_adverse_pct=6.5,
        )
    )
    assert not v.ok and v.code == "L1_PAST_INV", v
    print("OK kernel blocks Long1 at invalidation")


def test_blocks_overlapping_short() -> None:
    v = preflight_open(
        OpenIntent(
            symbol="X",
            leg="SHORT",
            side="SELL",
            qty=1,
            price=1,
            has_exchange_short=True,
        )
    )
    assert not v.ok and v.code == "OVERLAP_SHORT", v
    print("OK kernel blocks overlapping short")


def test_blocks_naked_short_at_10x() -> None:
    v = preflight_open(
        OpenIntent(
            symbol="BEAMXUSDT",
            leg="SHORT",
            side="SELL",
            qty=1000,
            price=0.003,
            exchange_leverage=10,
            has_exchange_long=False,
        )
    )
    assert not v.ok and v.code == "NAKED_SHORT_LEV", v
    print("OK kernel blocks naked short open at 10x")


def test_blocks_market_max() -> None:
    v = preflight_open(
        OpenIntent(
            symbol="BEAMXUSDT",
            leg="LONG1",
            side="BUY",
            qty=140056,
            price=0.0028,
            has_exchange_short=True,
            has_scanner_short=True,
            live_adverse_pct=2.1,
            market_max_qty=100000,
        )
    )
    assert not v.ok and v.code == "MARKET_MAX", v
    print("OK kernel blocks qty above MARKET max")


def test_allows_valid_long1() -> None:
    v = preflight_open(
        OpenIntent(
            symbol="X",
            leg="LONG1",
            side="BUY",
            qty=4,
            price=100,
            has_exchange_short=True,
            has_scanner_short=True,
            live_adverse_pct=2.1,
            market_max_qty=1_000_000,
        )
    )
    assert v.ok, v
    print("OK kernel allows valid Long1")


def test_solo_exit_blocked_in_episode() -> None:
    v = preflight_solo_hedge_exit(short_open=True, hedge_episode_active=True, short_underwater=False)
    assert not v.ok
    print("OK kernel blocks solo hedge exit in episode")


def test_watchdog_halts_naked_10x() -> None:
    codes = audit_live_state(
        LiveState(
            symbol="BEAMXUSDT",
            has_exchange_short=True,
            has_exchange_long=False,
            has_scanner_short=True,
            exchange_leverage=10,
        )
    )
    assert "NAKED_SHORT_AT_10X" in codes
    assert should_emergency_halt(codes)
    print("OK watchdog emergency-halts naked short at 10x")


def test_watchdog_halts_oversize_external() -> None:
    codes = audit_live_state(
        LiveState(
            symbol="AAVEUSDT",
            has_exchange_short=True,
            has_scanner_short=True,
            short_notional_usd=3479.0,
            max_short_notional_usd=250.0,
        )
    )
    assert "OVERSIZE_EXTERNAL_SHORT" in codes
    assert should_emergency_halt(codes)
    print("OK watchdog emergency-halts oversize external short")


if __name__ == "__main__":
    test_blocks_early_long1()
    test_blocks_long1_past_inv()
    test_blocks_overlapping_short()
    test_blocks_naked_short_at_10x()
    test_blocks_market_max()
    test_allows_valid_long1()
    test_solo_exit_blocked_in_episode()
    test_watchdog_halts_naked_10x()
    test_watchdog_halts_oversize_external()
    print("test_rule_kernel: ALL OK")
