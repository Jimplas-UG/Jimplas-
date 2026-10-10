"""
Frozen short-first strategy contract — do not change without an explicit product decision.

This module is a regression lock. It does NOT alter trading behavior; it verifies that
the live modules still match the working contract:

  Entry: 15m ≥5% gain + ≥0.7% retrace → SHORT (50% partition, 5x)
  +2% adverse from short → Long 1 BUY (40%, 10x)
  +4% adverse from short → Long 2 BUY (40%, 10x)
  While short underwater: hedges stay paired (no solo TP / 0.5% trail)
  Rescue: long PnL ≥ short loss + buffer → flatten all
  Invalidation: ≥6.5% adverse from short entry → flatten all
  Short TP −2.5%; never leave orphan longs without the primary short
  Hedged SHORT_TP / SHORT_PULLBACK flatten only when episode net clears exit costs
  (defer net-red hedged hard-TP — wait RESCUE / INVALIDATION / SMART_EXIT)
  Shared LONG close must never wipe/retire the sibling recovery leg
  (Long1 close must not permanently kill Long2, and vice versa)
  Smart exit: 6% of partition net — with hedges open, only when short is in profit
  Manual closes require confirm; REST cool on close waits up to 12s then clears
  Partition USD locked at $100 (Sep 23–25) — mainnet/testnet switch must not change it
  Permanent anti-cascade: no rule_kernel / SAFE_MODE; no instant cool-clear;
  PORTAL LONG-before-SHORT; adopt short notional ≤ 1.25×$250; liquidity ≥ $10M;
  episode/invalidation cool floors; Long settle ≥ 3s; 429 ≠ flat

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
PAIR_INVALIDATION_PCT = 6.5
HEDGE_RESCUE_BUFFER_PCT = 1.0

# Locked exit/ops discipline (profitable Sep 23–25 baseline) — do not weaken.
SMART_EXIT_NET_PCT = 6.0
SMART_EXIT_REQUIRES_SHORT_PROFIT_IF_HEDGED = True
CLOSE_REST_COOL_MAX_WAIT_S = 12.0
MANUAL_CLOSE_CONFIRM_REQUIRED = True
# Capital slice used on the winning Sep 23–25 desk — never $50 / never float with mode switch.
LOCKED_PARTITION_USD = 100.0
PARTITION_USD_LOCKED = True

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
            "paired_hold_while_underwater": True,
            "invalidation_pct": PAIR_INVALIDATION_PCT,
            "rescue_buffer_pct": HEDGE_RESCUE_BUFFER_PCT,
        },
        "entry": {
            "gain_pct": GAIN_THRESHOLD_PCT,
            "retrace_pct": RETRACE_ENTRY_PCT,
        },
        "tp": {"short_pct": SHORT_TP_PCT, "long_pct": LONG_TP_PCT},
        "ops": {
            "smart_exit_net_pct": SMART_EXIT_NET_PCT,
            "smart_exit_requires_short_profit_if_hedged": SMART_EXIT_REQUIRES_SHORT_PROFIT_IF_HEDGED,
            "close_rest_cool_max_wait_s": CLOSE_REST_COOL_MAX_WAIT_S,
            "manual_close_confirm_required": MANUAL_CLOSE_CONFIRM_REQUIRED,
            "partition_usd": LOCKED_PARTITION_USD,
            "partition_usd_locked": PARTITION_USD_LOCKED,
        },
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
    assert abs(float(ms.PAIR_INVALIDATION_PCT) - PAIR_INVALIDATION_PCT) < 1e-9
    assert abs(float(ms.HEDGE_RESCUE_BUFFER_PCT) - HEDGE_RESCUE_BUFFER_PCT) < 1e-9

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
    assert hasattr(ms.MomentumScanner, "_hedge_rescue_ready")
    assert hasattr(ms.MomentumScanner, "_pair_invalidation_hit")
    assert hasattr(ms.MomentumScanner, "_short_underwater")

    # AKEUSDT regression lock: sibling wipe on shared LONG must re-arm, never retire.
    assert hasattr(ms.MomentumScanner, "_repair_naked_short_hedges")
    assert hasattr(ms.MomentumScanner, "_safe_recovery_close_qty")
    assert hasattr(ms.MomentumScanner, "validate_open_pair_logic")
    src = open(ms.__file__, encoding="utf-8").read()
    assert "SIBLING_WIPE" in src, "sibling-wipe re-arm marker missing from momentum_scanner"
    assert "preserve sibling" in src, "safe recovery close qty guard missing"
    assert "def _safe_recovery_close_qty" in src
    assert "paired hold" in src.lower() or "PAIRED" in src or "_short_underwater" in src

    # Smart exit + close cool + hedged short-profit guard (Sep 23–25 baseline).
    assert abs(float(ms.SMART_EXIT_NET_PCT) - SMART_EXIT_NET_PCT) < 1e-9
    assert "short_ok_for_smart" in src, "SMART_EXIT hedged short-profit guard missing"
    assert SMART_EXIT_REQUIRES_SHORT_PROFIT_IF_HEDGED is True
    assert MANUAL_CLOSE_CONFIRM_REQUIRED is True

    # Partition USD lock — $100 only; must survive risk reload + mainnet/testnet login.
    assert abs(float(ms.LOCKED_PARTITION_USD) - LOCKED_PARTITION_USD) < 1e-9
    assert abs(float(ms.DEFAULT_PARTITION_USD) - LOCKED_PARTITION_USD) < 1e-9
    assert "force_locked_partition_usd" in src or "_force_locked_partition_usd" in src
    assert "PARTITION_USD_LOCKED" in src or "locked partition" in src.lower()

    import inspect
    import binance_connector as bc

    cool_src = inspect.getsource(bc.BinanceConnector._wait_or_clear_cool_for_close)
    assert "max_wait_s: float = 12.0" in cool_src, "close REST cool default must stay 12s"
    assert "waiting" in cool_src and "clearing residual cool" in cool_src
    assert "immediate flatten" not in cool_src, "instant cool-clear must never return"
    assert "forced to 12s" in cool_src or "ignoring max_wait_s" in cool_src

    # Capital locks restored on Sep23 core (no Oct cascade/halt layers).
    assert hasattr(ms.MomentumScanner, "_hedge_episode_active")
    assert hasattr(ms.MomentumScanner, "_solo_hedge_exit_allowed")
    assert hasattr(ms.MomentumScanner, "clamp_manual_open_qty")
    assert "PAIR_INVALIDATION_PCT" in inspect.getsource(ms.MomentumScanner._long1_entry_allowed)
    assert "PAIR_INVALIDATION_PCT" in inspect.getsource(ms.MomentumScanner._long2_entry_allowed)
    manage_src = inspect.getsource(ms.MomentumScanner._manage_positions)
    assert "target = LONG1_LEVERAGE" not in manage_src
    assert "symbol_exchange_leverage" in manage_src
    # Hedged SHORT_TP must share SHORT_PULLBACK's net-clear gate (no net-red flatten).
    assert hasattr(ms.MomentumScanner, "_hedged_short_exit_net_ok")
    assert "_hedged_short_exit_net_ok" in manage_src
    assert "defer" in manage_src
    assert "marketMaxQty" in inspect.getsource(bc.BinanceConnector._parse_symbol_filters)
    assert "long_residual_abort_short" in inspect.getsource(bc.BinanceConnector.close_position)
    side_src = inspect.getsource(bc.BinanceConnector.close_by_position_side)
    assert "marketMaxQty" in side_src or "market_max" in side_src
    assert "too_many_close_chunks" in side_src
    assert "long_residual_abort_short" in side_src, "PORTAL: SHORT close must refuse LONG residual"
    assert "-2022" in side_src or "reduceonly" in side_src.lower()
    close_src = inspect.getsource(bc.BinanceConnector.close_position)
    assert "-2022" in close_src or "reduceonly" in close_src.lower()
    pos_src = inspect.getsource(bc.BinanceConnector.positions)
    assert "unavailable — not empty" in pos_src
    assert "PositionsUnavailable" in pos_src
    assert hasattr(bc, "PositionsUnavailable")
    # force=True must never invent flat from REST errors (false SHORT_GONE / orphan).
    assert "raise PositionsUnavailable" in pos_src
    recon_src = inspect.getsource(ms.MomentumScanner._reconcile_from_exchange_locked)
    assert "positions_unavailable" in recon_src or "PositionsUnavailable" in recon_src
    coh_src = inspect.getsource(ms.MomentumScanner._ensure_pair_coherence)
    assert "coherence deferred" in coh_src

    # Permanent anti-cascade / anti-drift locks (Oct forensic — never reintroduce).
    from pathlib import Path as _Path

    assert not _Path(ms.__file__).with_name("rule_kernel.py").exists(), "rule_kernel.py must stay deleted"
    assert "SAFE_MODE" not in src, "SAFE_MODE cascade must never return to momentum_scanner"
    assert "rule_kernel" not in src.lower()
    assert float(ms.MIN_QUOTE_VOL_24H) >= 10_000_000.0
    assert int(ms.INVALIDATION_COOLDOWN_MS) >= 1_200_000
    assert int(ms.EPISODE_COOLDOWN_MS) >= 600_000
    assert int(ms.ENTRY_COOLDOWN_MS) >= 300_000
    assert int(ms.LONG_ENTRY_DELAY_MS) >= 3_000
    assert hasattr(ms.MomentumScanner, "_short_notional_within_partition")
    assert hasattr(ms.MomentumScanner, "_locked_short_notional_usd")
    assert "notional" in inspect.getsource(ms.MomentumScanner._adopt_exchange_short)
    main_path = _Path(ms.__file__).with_name("main.py")
    main_src = main_path.read_text(encoding="utf-8")
    assert "_force_positions_or_503" in main_src
    assert "PositionsUnavailable" in main_src

    return frozen_contract_snapshot()


def verify_frozen_contract_or_raise() -> dict[str, Any]:
    """Alias used by bridge startup."""
    return assert_frozen_contract()
