"""
Hard strategy policy floors — cannot be bypassed by env, risk JSON, or app UI.

Short-first strategy: primary short 50% / 5x, recovery longs 40% + 40% / 10x.
The floors here protect the pieces that previously drifted into losses:
- the PRIMARY short trail collapsing to a 0.5% hard stop before recovery longs armed
- smart exit at ~0.4% price (1% of partition)
- recovery leg sizing scaled so far off policy that the hedge stopped working

The recovery Long 1 / Long 2 peak retrace stays at 0.5% by design and is NOT clamped
here — it is a take-profit trail on a hedge leg, not a stop on the primary leg.
"""

from __future__ import annotations

from leverage_policy import LONG1_LEVERAGE, SHORT_LEVERAGE

# Absolute floors / ceilings — raising env is OK; lowering below these is not.
MIN_PULLBACK_PCT = 1.5
MIN_PULLBACK_MFE_PCT = 1.5
# 0 disables smart exit; any positive value is forced to at least this.
MIN_SMART_EXIT_PCT_IF_ENABLED = 6.0
MIN_EXIT_COST_BUFFER_PCT = 0.5

# Policy sizing: primary short 50%, each recovery long 40%.
SAFE_PRIMARY_SHORT_PCT = 50.0
SAFE_RECOVERY_LEG_PCT = 40.0
MIN_RECOVERY_LEG_PCT = 5.0
MAX_RECOVERY_LEG_PCT = 50.0
# 40+40 @10x vs 50 @5x = 3.2 — allow the original ratio with a little headroom only.
MAX_RECOVERY_VS_PRIMARY_NOTIONAL = 3.3
# Long-first era clamped both recovery legs to 12.5% — migrate that back to policy.
LEGACY_CLAMPED_RECOVERY_PCT = 12.5

# Backwards-compatible alias — kept so older config readers keep importing cleanly.
SAFE_LONG_PARTITION_PCT = SAFE_PRIMARY_SHORT_PCT


def clamp_pullback_pct(value: float) -> float:
    return max(float(value or 0), MIN_PULLBACK_PCT)


def clamp_pullback_mfe_pct(value: float) -> float:
    return max(float(value or 0), MIN_PULLBACK_MFE_PCT)


def clamp_smart_exit_pct(value: float) -> float:
    v = float(value or 0)
    if v <= 0:
        return 0.0
    return max(v, MIN_SMART_EXIT_PCT_IF_ENABLED)


def clamp_exit_cost_pct(value: float) -> float:
    return max(float(value or 0), MIN_EXIT_COST_BUFFER_PCT)


def primary_notional_mult(short_partition_pct: float) -> float:
    """Dollar notional multiplier of the primary short leg."""
    return max(float(short_partition_pct), 1.0) / 100.0 * SHORT_LEVERAGE


def recovery_notional_mult(long1_pct: float, long2_pct: float) -> float:
    """Combined dollar notional multiplier of the recovery long legs."""
    return (max(float(long1_pct), 0.0) + max(float(long2_pct), 0.0)) / 100.0 * LONG1_LEVERAGE


def _is_legacy_clamped(long1_pct: float, long2_pct: float) -> bool:
    """Detect the long-first 12.5/12.5 clamp that replaced the original 40/40."""
    return (
        abs(float(long1_pct) - LEGACY_CLAMPED_RECOVERY_PCT) < 1e-6
        and abs(float(long2_pct) - LEGACY_CLAMPED_RECOVERY_PCT) < 1e-6
    )


def sanitize_partitions(
    short_pct: float,
    long1_pct: float,
    long2_pct: float,
) -> tuple[float, float, float, bool]:
    """
    Keep short-first sizing inside policy. Returns (short, long1, long2, changed).
    The original 50 / 40 / 40 passes through untouched.
    """
    short_u = max(1.0, min(100.0, float(short_pct)))
    l1 = max(MIN_RECOVERY_LEG_PCT, min(MAX_RECOVERY_LEG_PCT, float(long1_pct)))
    l2 = max(MIN_RECOVERY_LEG_PCT, min(MAX_RECOVERY_LEG_PCT, float(long2_pct)))
    changed = (
        abs(l1 - float(long1_pct)) > 1e-9
        or abs(l2 - float(long2_pct)) > 1e-9
        or abs(short_u - float(short_pct)) > 1e-9
    )

    # Migrate the long-first clamp back to the original recovery sizing.
    if _is_legacy_clamped(long1_pct, long2_pct):
        l1 = SAFE_RECOVERY_LEG_PCT
        l2 = SAFE_RECOVERY_LEG_PCT
        if short_u < SAFE_PRIMARY_SHORT_PCT:
            short_u = SAFE_PRIMARY_SHORT_PCT
        changed = True

    primary_n = primary_notional_mult(short_u)
    recovery_n = recovery_notional_mult(l1, l2)
    max_recovery_n = primary_n * MAX_RECOVERY_VS_PRIMARY_NOTIONAL
    if recovery_n > max_recovery_n + 1e-9 and recovery_n > 0:
        scale = max_recovery_n / recovery_n
        l1 = max(MIN_RECOVERY_LEG_PCT, min(MAX_RECOVERY_LEG_PCT, l1 * scale))
        l2 = max(MIN_RECOVERY_LEG_PCT, min(MAX_RECOVERY_LEG_PCT, l2 * scale))
        # If still over (min floors), snap to policy defaults.
        if recovery_notional_mult(l1, l2) > max_recovery_n + 1e-9:
            l1 = SAFE_RECOVERY_LEG_PCT
            l2 = SAFE_RECOVERY_LEG_PCT
            short_u = SAFE_PRIMARY_SHORT_PCT
        changed = True

    return short_u, round(l1, 4), round(l2, 4), changed


def is_toxic_legacy_sizing(short_pct: float, long1_pct: float, long2_pct: float) -> bool:
    """True when persisted sizing is off-policy and must be migrated on load."""
    if _is_legacy_clamped(long1_pct, long2_pct):
        return True
    primary_n = primary_notional_mult(short_pct)
    recovery_n = recovery_notional_mult(long1_pct, long2_pct)
    return primary_n > 0 and recovery_n / primary_n > MAX_RECOVERY_VS_PRIMARY_NOTIONAL + 1e-9
