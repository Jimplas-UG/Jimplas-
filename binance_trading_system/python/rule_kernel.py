"""
Hard rule kernel — single choke point so frozen locks cannot be bypassed.

Every OPEN (scanner or manual) must pass preflight_open() inside ExecutionEngine.
Live state is audited by audit_live_state(); hard breaches emergency-halt new entries.

This module does NOT change strategy knobs — it enforces short_first_v1 locks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from frozen_strategy import (
    LOCKED_PARTITION_USD,
    LONG1_ADVERSE_PCT,
    LONG2_ADVERSE_PCT,
    PAIR_INVALIDATION_PCT,
    PRIMARY_LEVERAGE,
    PRIMARY_PARTITION_PCT,
    RECOVERY_LEVERAGE,
    RECOVERY_PARTITION_PCT,
)

# Hard breach codes — watchdog emergency-halts on these.
HALT_ON = frozenset(
    {
        "NAKED_SHORT_AT_10X",
        "OVERLAPPING_EXCHANGE_SHORT",
        "HEDGE_PAST_INVALIDATION",
        "RULE_KERNEL_BYPASS",
    }
)


@dataclass
class OpenIntent:
    """Everything the kernel needs to allow or reject an open."""

    symbol: str
    leg: str
    side: str
    qty: float
    price: float
    manual: bool = False
    # Live pair state
    has_exchange_short: bool = False
    has_exchange_long: bool = False
    has_scanner_short: bool = False
    has_long1: bool = False
    has_long2: bool = False
    long1_was_closed: bool = False
    long2_was_closed: bool = False
    short_entry: float = 0.0
    live_adverse_pct: float = 0.0
    exchange_leverage: int | None = None
    market_max_qty: float = 0.0
    partition_usd: float = LOCKED_PARTITION_USD
    short_pct: float = PRIMARY_PARTITION_PCT
    long1_pct: float = RECOVERY_PARTITION_PCT


@dataclass
class LiveState:
    """Snapshot for continuous audit (watchdog)."""

    symbol: str
    has_exchange_short: bool = False
    has_exchange_long: bool = False
    has_scanner_short: bool = False
    has_long1: bool = False
    has_long2: bool = False
    live_adverse_pct: float = 0.0
    exchange_leverage: int | None = None
    scanner_short_qty: float = 0.0
    exchange_short_qty: float = 0.0


@dataclass
class KernelVerdict:
    ok: bool
    reason: str = ""
    code: str = ""


def _max_leg_qty(price: float, leverage: int, partition_pct: float, partition_usd: float) -> float:
    if price <= 0:
        return 0.0
    return (partition_usd * partition_pct / 100.0 * leverage) / price


def preflight_open(intent: OpenIntent) -> KernelVerdict:
    """Return ok=False to hard-block the order before Binance sees it."""
    leg = (intent.leg or "").upper()
    side = (intent.side or "").upper()
    qty = float(intent.qty or 0)
    px = float(intent.price or 0)
    if qty <= 0 or px <= 0:
        return KernelVerdict(False, "kernel_invalid_qty_or_price", "INVALID_INPUT")

    part = float(intent.partition_usd or LOCKED_PARTITION_USD)
    if abs(part - LOCKED_PARTITION_USD) > 1e-6:
        return KernelVerdict(False, f"kernel_partition_not_locked:{part}", "PARTITION_DRIFT")

    # MARKET max — never -4005 naked path
    mmax = float(intent.market_max_qty or 0)
    if mmax > 0 and qty > mmax * 1.001:
        return KernelVerdict(False, f"kernel_qty_above_market_max:{qty}>{mmax}", "MARKET_MAX")

    if leg == "SHORT" or (intent.manual and side == "SELL"):
        if intent.has_exchange_short and not intent.manual:
            return KernelVerdict(False, "kernel_overlapping_short", "OVERLAP_SHORT")
        max_q = _max_leg_qty(px, PRIMARY_LEVERAGE, intent.short_pct, part)
        if max_q > 0 and qty > max_q * 1.02:
            return KernelVerdict(False, f"kernel_short_oversize:{qty}>{max_q}", "SIZE_CAP")
        # Naked short must open at 5x — refuse if exchange already stuck above 5x while flat of longs.
        if (
            not intent.manual
            and intent.exchange_leverage is not None
            and int(intent.exchange_leverage) > PRIMARY_LEVERAGE
            and not intent.has_exchange_long
        ):
            return KernelVerdict(
                False,
                f"kernel_naked_short_lev_{intent.exchange_leverage}_not_5",
                "NAKED_SHORT_LEV",
            )
        return KernelVerdict(True)

    if leg == "LONG1" or (intent.manual and side == "BUY" and leg == "MANUAL"):
        if leg == "LONG1":
            if not intent.has_exchange_short and not intent.has_scanner_short:
                return KernelVerdict(False, "kernel_long1_without_short", "L1_NO_SHORT")
            if intent.has_long1:
                return KernelVerdict(False, "kernel_long1_already_open", "L1_DUP")
            adv = float(intent.live_adverse_pct or 0)
            if adv >= PAIR_INVALIDATION_PCT:
                return KernelVerdict(False, f"kernel_long1_past_inv:{adv:.2f}", "L1_PAST_INV")
            if adv + 1e-9 < LONG1_ADVERSE_PCT:
                return KernelVerdict(False, f"kernel_long1_early:{adv:.2f}", "L1_EARLY")
        max_q = _max_leg_qty(px, RECOVERY_LEVERAGE, intent.long1_pct, part)
        if max_q > 0 and qty > max_q * 1.02:
            # Allow clamped market-max fills below partition when market max binds.
            if not (mmax > 0 and qty <= mmax * 1.001):
                return KernelVerdict(False, f"kernel_long_oversize:{qty}>{max_q}", "SIZE_CAP")
        return KernelVerdict(True)

    if leg == "LONG2":
        if not intent.has_exchange_short and not intent.has_scanner_short:
            return KernelVerdict(False, "kernel_long2_without_short", "L2_NO_SHORT")
        if intent.has_long2:
            return KernelVerdict(False, "kernel_long2_already_open", "L2_DUP")
        # Ordered recovery: Long1 must exist or have been intentionally closed (sibling wipe re-arm).
        if not intent.has_long1 and not intent.long1_was_closed:
            return KernelVerdict(False, "kernel_long2_before_long1", "L2_ORDER")
        adv = float(intent.live_adverse_pct or 0)
        if adv >= PAIR_INVALIDATION_PCT:
            return KernelVerdict(False, f"kernel_long2_past_inv:{adv:.2f}", "L2_PAST_INV")
        if adv + 1e-9 < LONG2_ADVERSE_PCT:
            return KernelVerdict(False, f"kernel_long2_early:{adv:.2f}", "L2_EARLY")
        max_q = _max_leg_qty(px, RECOVERY_LEVERAGE, intent.long1_pct, part)
        if max_q > 0 and qty > max_q * 1.02:
            if not (mmax > 0 and qty <= mmax * 1.001):
                return KernelVerdict(False, f"kernel_long_oversize:{qty}>{max_q}", "SIZE_CAP")
        return KernelVerdict(True)

    if leg == "MANUAL":
        # Size already checked via SELL/BUY branches when side known; default allow after size.
        return KernelVerdict(True)

    return KernelVerdict(False, f"kernel_unknown_leg:{leg}", "UNKNOWN_LEG")


def preflight_solo_hedge_exit(
    *,
    short_open: bool,
    hedge_episode_active: bool,
    short_underwater: bool,
) -> KernelVerdict:
    """Block solo Long1/Long2 TP/pullback once a hedge episode is active or short is red."""
    if not short_open:
        return KernelVerdict(True)
    if short_underwater:
        return KernelVerdict(False, "kernel_solo_exit_short_underwater", "SOLO_EXIT_BLOCK")
    if hedge_episode_active:
        return KernelVerdict(False, "kernel_solo_exit_hedge_episode", "SOLO_EXIT_BLOCK")
    return KernelVerdict(True)


def audit_live_state(state: LiveState) -> list[str]:
    """Return violation codes for an open symbol. Empty = clean."""
    codes: list[str] = []
    if state.has_exchange_short and state.has_scanner_short:
        sq = float(state.scanner_short_qty or 0)
        eq = float(state.exchange_short_qty or 0)
        # Rough overlap: exchange short much larger than one scanner leg → stacked.
        if sq > 0 and eq > sq * 1.85:
            codes.append("OVERLAPPING_EXCHANGE_SHORT")
    naked = state.has_exchange_short and not state.has_exchange_long and not state.has_long1 and not state.has_long2
    if naked and state.exchange_leverage is not None and int(state.exchange_leverage) >= 10:
        codes.append("NAKED_SHORT_AT_10X")
    if (state.has_long1 or state.has_long2) and float(state.live_adverse_pct or 0) >= PAIR_INVALIDATION_PCT + 0.05:
        # Hedge still open past invalidation — manage should have flattened; flag hard.
        codes.append("HEDGE_PAST_INVALIDATION")
    return codes


def should_emergency_halt(codes: list[str]) -> bool:
    return any(c in HALT_ON for c in codes)
