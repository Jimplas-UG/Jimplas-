"""
Frozen long-first strategy contract — do not change without an explicit product decision.

This module is a regression lock. It does NOT alter trading behavior; it verifies that
the live modules still match the working contract:

  Entry: 15m ≥5% gain + ≥0.7% retrace → LONG (50% partition, 5x)
  −2% adverse from long → Short 1 SELL (~12.5%, 10x)
  −4% adverse from long → Short 2 SELL (~12.5%, 10x)
  Each leg TP ±2.5%; trail only after profitable MFE (never a 0.5% hard stop)
  Never leave orphan shorts without the primary long
  Short1+Short2 notional capped ~1:1 vs the long (40/40 is toxic)

If assert_frozen_contract() fails, the bridge must not silently trade a drifted policy.
"""

from __future__ import annotations

from typing import Any

STRATEGY_ID = "long_first_v1"
STRATEGY_NAME = "Long → Short 1 → Short 2"

# Canonical knobs — must match module defaults.
PRIMARY_LEG = "LONG1"
PRIMARY_SIDE = "BUY"
PRIMARY_MAGIC = 88002
PRIMARY_PARTITION_PCT = 50.0
PRIMARY_LEVERAGE = 5

RECOVERY_LEG_1 = "SHORT"
RECOVERY_LEG_2 = "LONG2"
RECOVERY_SIDE = "SELL"
RECOVERY_MAGIC_1 = 88001
RECOVERY_MAGIC_2 = 88003
RECOVERY_PARTITION_PCT = 12.5
RECOVERY_LEVERAGE = 10

GAIN_THRESHOLD_PCT = 5.0
RETRACE_ENTRY_PCT = 0.7
LONG1_ADVERSE_PCT = 2.0
LONG2_ADVERSE_PCT = 4.0
SHORT_TP_PCT = 2.5
LONG_TP_PCT = 2.5
TRAIL_PULLBACK_FLOOR_PCT = 1.5

STATUS_LONG = "Long"
STATUS_SHORT1 = "Short 1"
STATUS_SHORT2 = "Short 2"

# Forbidden short-first status labels that invert the desk.
FORBIDDEN_STATUSES = frozenset({"Short", "Long 1", "Long 2"})


def frozen_contract_snapshot() -> dict[str, Any]:
    return {
        "strategy_id": STRATEGY_ID,
        "strategy_name": STRATEGY_NAME,
        "primary": {
            "leg": PRIMARY_LEG,
            "side": PRIMARY_SIDE,
            "magic": PRIMARY_MAGIC,
            "partition_pct": PRIMARY_PARTITION_PCT,
            "leverage": PRIMARY_LEVERAGE,
            "status": STATUS_LONG,
        },
        "recovery": {
            "leg1": RECOVERY_LEG_1,
            "leg2": RECOVERY_LEG_2,
            "side": RECOVERY_SIDE,
            "magic1": RECOVERY_MAGIC_1,
            "magic2": RECOVERY_MAGIC_2,
            "partition_pct": RECOVERY_PARTITION_PCT,
            "leverage": RECOVERY_LEVERAGE,
            "status1": STATUS_SHORT1,
            "status2": STATUS_SHORT2,
            "adverse1_pct": LONG1_ADVERSE_PCT,
            "adverse2_pct": LONG2_ADVERSE_PCT,
            "pullback_floor_pct": TRAIL_PULLBACK_FLOOR_PCT,
        },
        "entry": {
            "gain_pct": GAIN_THRESHOLD_PCT,
            "retrace_pct": RETRACE_ENTRY_PCT,
        },
        "tp": {"short_pct": SHORT_TP_PCT, "long_pct": LONG_TP_PCT},
    }


def assert_frozen_contract() -> dict[str, Any]:
    """
    Import live modules and assert they still match the frozen long-first contract.
    Raises AssertionError on drift. Returns the contract snapshot on success.
    """
    import leverage_policy as lev
    import momentum_scanner as ms
    from binance_connector import close_leg_sides
    from strategy_guards import sanitize_partitions

    # Status labels — Long / Short 1 / Short 2
    assert ms.STATUS_LONG1 == STATUS_LONG, f"STATUS_LONG1 drifted: {ms.STATUS_LONG1!r}"
    assert ms.STATUS_SHORT == STATUS_SHORT1, f"STATUS_SHORT drifted: {ms.STATUS_SHORT!r}"
    assert ms.STATUS_LONG2 == STATUS_SHORT2, f"STATUS_LONG2 drifted: {ms.STATUS_LONG2!r}"
    for bad in FORBIDDEN_STATUSES:
        assert ms.STATUS_SHORT != bad and ms.STATUS_LONG1 != bad and ms.STATUS_LONG2 != bad

    # Magics / direction mapping (Long BUY, Short1/Short2 SELL).
    assert ms.MAGIC_LONG1 == PRIMARY_MAGIC
    assert ms.MAGIC_SHORT == RECOVERY_MAGIC_1
    assert ms.MAGIC_LONG2 == RECOVERY_MAGIC_2
    assert close_leg_sides(PRIMARY_MAGIC) == ("SELL", "LONG")
    assert close_leg_sides(RECOVERY_MAGIC_1) == ("BUY", "SHORT")
    assert close_leg_sides(RECOVERY_MAGIC_2) == ("BUY", "SHORT")

    # Leverage policy: primary Long BUY 5x; recovery shorts 10x.
    assert lev.SHORT_LEVERAGE == PRIMARY_LEVERAGE
    assert lev.LONG1_LEVERAGE == RECOVERY_LEVERAGE
    assert lev.LONG2_LEVERAGE == RECOVERY_LEVERAGE
    assert lev.sizing_leverage("LONG1", "BUY") == PRIMARY_LEVERAGE
    assert lev.sizing_leverage("SHORT", "SELL") == PRIMARY_LEVERAGE  # manual/short label at 5x base
    assert lev.sizing_leverage("LONG1", "SELL") == RECOVERY_LEVERAGE
    assert lev.sizing_leverage("LONG2", "SELL") == RECOVERY_LEVERAGE

    # Entry / adverse / TP / trail floors.
    assert abs(ms.GAIN_THRESHOLD_PCT - GAIN_THRESHOLD_PCT) < 1e-9
    assert abs(ms.RETRACE_ENTRY_PCT - RETRACE_ENTRY_PCT) < 1e-9
    assert abs(ms.LONG1_ADVERSE_PCT - LONG1_ADVERSE_PCT) < 1e-9
    assert abs(ms.LONG2_ADVERSE_PCT - LONG2_ADVERSE_PCT) < 1e-9
    assert abs(ms.SHORT_TP_PCT - SHORT_TP_PCT) < 1e-9
    assert abs(ms.LONG_TP_PCT - LONG_TP_PCT) < 1e-9
    assert float(ms.LONG_BOTH_PULLBACK_PCT) + 1e-9 >= TRAIL_PULLBACK_FLOOR_PCT

    # Partition policy: 50 / 12.5 / 12.5 (sanitize arg order: long, short1, short2).
    long_p, s1, s2, changed = sanitize_partitions(
        PRIMARY_PARTITION_PCT, RECOVERY_PARTITION_PCT, RECOVERY_PARTITION_PCT
    )
    assert not changed
    assert abs(long_p - PRIMARY_PARTITION_PCT) < 1e-9
    assert abs(s1 - RECOVERY_PARTITION_PCT) < 1e-9
    assert abs(s2 - RECOVERY_PARTITION_PCT) < 1e-9
    # Module uses SHORT_PARTITION_PCT as the primary long bucket in long-first.
    assert abs(float(ms.SHORT_PARTITION_PCT) - PRIMARY_PARTITION_PCT) < 1e-6
    assert abs(float(ms.LONG1_PARTITION_PCT) - RECOVERY_PARTITION_PCT) < 1e-6
    assert abs(float(ms.LONG2_PARTITION_PCT) - RECOVERY_PARTITION_PCT) < 1e-6

    # Primary open path must exist; recovery opens must be SELL hedges.
    assert hasattr(ms.MomentumScanner, "_try_open_long1_entry")
    assert hasattr(ms.MomentumScanner, "_try_open_short1")
    assert hasattr(ms.MomentumScanner, "_try_open_short2")
    assert hasattr(ms.MomentumScanner, "reconcile_from_exchange")
    assert hasattr(ms.MomentumScanner, "adopt_open_strategies_from_exchange")

    return frozen_contract_snapshot()


def verify_frozen_contract_or_raise() -> dict[str, Any]:
    """Alias used by bridge startup."""
    return assert_frozen_contract()
