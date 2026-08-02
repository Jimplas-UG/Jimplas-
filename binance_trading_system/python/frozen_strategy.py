"""
Frozen short-first strategy contract — do not change without an explicit product decision.

This module is a regression lock. It does NOT alter trading behavior; it verifies that
the live modules still match the working contract:

  Entry: 15m ≥5% gain + ≥0.7% retrace → SHORT (50% partition, 5x)
  +2% adverse from short → Long 1 BUY (40%, 10x), close on 0.5% peak retrace
  +4% adverse from short → Long 2 BUY (40%, 10x), close on 0.5% peak retrace
  Short TP −2.5%; never leave orphan longs without the primary short
  Shared LONG close must never wipe/retire the sibling recovery leg
  (Long1 close must not permanently kill Long2, and vice versa)

If assert_frozen_contract() fails, the bridge must not silently trade a drifted policy.
"""

from __future__ import annotations

from typing import Any

STRATEGY_ID = "short_first_v1"
STRATEGY_NAME = "Short → Long 1 → Long 2"

# Canonical knobs — must match module defaults (env may raise floors, not invert direction).
PRIMARY_LEG = "SHORT"
PRIMARY_SIDE = "SELL"
PRIMARY_MAGIC = 88001
PRIMARY_PARTITION_PCT = 50.0
PRIMARY_LEVERAGE = 5

RECOVERY_LEG_1 = "LONG1"
RECOVERY_LEG_2 = "LONG2"
RECOVERY_SIDE = "BUY"
RECOVERY_MAGIC_1 = 88002
RECOVERY_MAGIC_2 = 88003
RECOVERY_PARTITION_PCT = 40.0
RECOVERY_LEVERAGE = 10

GAIN_THRESHOLD_PCT = 5.0
RETRACE_ENTRY_PCT = 0.7
LONG1_ADVERSE_PCT = 2.0
LONG2_ADVERSE_PCT = 4.0
SHORT_TP_PCT = 2.5
LONG_TP_PCT = 2.5
LONG_HEDGE_PULLBACK_PCT = 0.5
SHORT_TRAIL_PULLBACK_FLOOR_PCT = 1.5

STATUS_SHORT = "Short"
STATUS_LONG1 = "Long 1"
STATUS_LONG2 = "Long 2"

# Forbidden long-first status labels that previously inverted the desk.
FORBIDDEN_STATUSES = frozenset({"Short 1", "Short 2", "Long"})


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
            "status": STATUS_SHORT,
        },
        "recovery": {
            "leg1": RECOVERY_LEG_1,
            "leg2": RECOVERY_LEG_2,
            "side": RECOVERY_SIDE,
            "magic1": RECOVERY_MAGIC_1,
            "magic2": RECOVERY_MAGIC_2,
            "partition_pct": RECOVERY_PARTITION_PCT,
            "leverage": RECOVERY_LEVERAGE,
            "status1": STATUS_LONG1,
            "status2": STATUS_LONG2,
            "adverse1_pct": LONG1_ADVERSE_PCT,
            "adverse2_pct": LONG2_ADVERSE_PCT,
            "pullback_pct": LONG_HEDGE_PULLBACK_PCT,
        },
        "entry": {
            "gain_pct": GAIN_THRESHOLD_PCT,
            "retrace_pct": RETRACE_ENTRY_PCT,
        },
        "tp": {"short_pct": SHORT_TP_PCT, "long_pct": LONG_TP_PCT},
    }


def assert_frozen_contract() -> dict[str, Any]:
    """
    Import live modules and assert they still match the frozen short-first contract.
    Raises AssertionError on drift. Returns the contract snapshot on success.
    """
    import leverage_policy as lev
    import momentum_scanner as ms
    from binance_connector import close_leg_sides
    from strategy_guards import sanitize_partitions

    # Status labels — never silently flip back to long-first UI strings.
    assert ms.STATUS_SHORT == STATUS_SHORT, f"STATUS_SHORT drifted: {ms.STATUS_SHORT!r}"
    assert ms.STATUS_LONG1 == STATUS_LONG1, f"STATUS_LONG1 drifted: {ms.STATUS_LONG1!r}"
    assert ms.STATUS_LONG2 == STATUS_LONG2, f"STATUS_LONG2 drifted: {ms.STATUS_LONG2!r}"
    for bad in FORBIDDEN_STATUSES:
        assert ms.STATUS_SHORT != bad and ms.STATUS_LONG1 != bad and ms.STATUS_LONG2 != bad

    # Magics / direction mapping.
    assert ms.MAGIC_SHORT == PRIMARY_MAGIC
    assert ms.MAGIC_LONG1 == RECOVERY_MAGIC_1
    assert ms.MAGIC_LONG2 == RECOVERY_MAGIC_2
    assert close_leg_sides(PRIMARY_MAGIC) == ("BUY", "SHORT")
    assert close_leg_sides(RECOVERY_MAGIC_1) == ("SELL", "LONG")
    assert close_leg_sides(RECOVERY_MAGIC_2) == ("SELL", "LONG")

    # Leverage policy.
    assert lev.SHORT_LEVERAGE == PRIMARY_LEVERAGE
    assert lev.LONG1_LEVERAGE == RECOVERY_LEVERAGE
    assert lev.LONG2_LEVERAGE == RECOVERY_LEVERAGE
    assert lev.sizing_leverage("SHORT", "SELL") == PRIMARY_LEVERAGE
    assert lev.sizing_leverage("LONG1", "BUY") == RECOVERY_LEVERAGE
    assert lev.sizing_leverage("LONG2", "BUY") == RECOVERY_LEVERAGE

    # Entry / adverse / TP / hedge pullback defaults (floors may raise short trail only).
    assert abs(ms.GAIN_THRESHOLD_PCT - GAIN_THRESHOLD_PCT) < 1e-9
    assert abs(ms.RETRACE_ENTRY_PCT - RETRACE_ENTRY_PCT) < 1e-9
    assert abs(ms.LONG1_ADVERSE_PCT - LONG1_ADVERSE_PCT) < 1e-9
    assert abs(ms.LONG2_ADVERSE_PCT - LONG2_ADVERSE_PCT) < 1e-9
    assert abs(ms.SHORT_TP_PCT - SHORT_TP_PCT) < 1e-9
    assert abs(ms.LONG_TP_PCT - LONG_TP_PCT) < 1e-9
    assert abs(float(ms.LONG_HEDGE_PULLBACK_PCT) - LONG_HEDGE_PULLBACK_PCT) < 1e-9
    assert float(ms.SHORT_TRAIL_PULLBACK_PCT) + 1e-9 >= SHORT_TRAIL_PULLBACK_FLOOR_PCT

    # Partition policy: 50/40/40 must pass through unchanged.
    s, l1, l2, changed = sanitize_partitions(
        PRIMARY_PARTITION_PCT, RECOVERY_PARTITION_PCT, RECOVERY_PARTITION_PCT
    )
    assert not changed
    assert abs(s - PRIMARY_PARTITION_PCT) < 1e-9
    assert abs(l1 - RECOVERY_PARTITION_PCT) < 1e-9
    assert abs(l2 - RECOVERY_PARTITION_PCT) < 1e-9
    # After sanitize at import, module defaults must still be policy.
    assert abs(float(ms.SHORT_PARTITION_PCT) - PRIMARY_PARTITION_PCT) < 1e-6
    assert abs(float(ms.LONG1_PARTITION_PCT) - RECOVERY_PARTITION_PCT) < 1e-6
    assert abs(float(ms.LONG2_PARTITION_PCT) - RECOVERY_PARTITION_PCT) < 1e-6

    # Primary open path must exist; recovery opens must be BUY hedges.
    assert hasattr(ms.MomentumScanner, "_try_open_short_entry")
    assert hasattr(ms.MomentumScanner, "_try_open_long1")
    assert hasattr(ms.MomentumScanner, "_try_open_long2")
    assert hasattr(ms.MomentumScanner, "adopt_open_strategies_from_exchange")

    # AKEUSDT regression lock: sibling wipe on shared LONG must re-arm, never retire.
    assert hasattr(ms.MomentumScanner, "_repair_naked_short_hedges")
    assert hasattr(ms.MomentumScanner, "_safe_recovery_close_qty")
    assert hasattr(ms.MomentumScanner, "validate_open_pair_logic")
    src = open(ms.__file__, encoding="utf-8").read()
    assert "SIBLING_WIPE" in src, "sibling-wipe re-arm marker missing from momentum_scanner"
    assert "preserve sibling" in src, "safe recovery close qty guard missing"
    assert "def _safe_recovery_close_qty" in src

    return frozen_contract_snapshot()


def verify_frozen_contract_or_raise() -> dict[str, Any]:
    """Alias used by bridge startup."""
    return assert_frozen_contract()
