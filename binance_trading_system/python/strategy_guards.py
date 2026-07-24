"""
Hard strategy policy floors — cannot be bypassed by env, risk JSON, or app UI.

These exist because live losses (-$600+) came from soft knobs drifting back to:
- 0.5% peak pullback acting as a hard stop before Short1/Short2
- smart exit at ~0.4% price (1% of partition)
- Short1+Short2 40%/40% ×10x ≈ 3.2:1 short-heavy notional
"""

from __future__ import annotations

from leverage_policy import LONG1_LEVERAGE, SHORT_LEVERAGE

# Absolute floors / ceilings — raising env is OK; lowering below these is not.
MIN_PULLBACK_PCT = 1.5
MIN_PULLBACK_MFE_PCT = 1.5
# 0 disables smart exit; any positive value is forced to at least this.
MIN_SMART_EXIT_PCT_IF_ENABLED = 6.0
MIN_EXIT_COST_BUFFER_PCT = 0.5
MAX_SHORT_VS_LONG_NOTIONAL = 1.25
MAX_RECOVERY_LEG_PCT = 15.0
MIN_RECOVERY_LEG_PCT = 5.0
SAFE_RECOVERY_LEG_PCT = 12.5
SAFE_LONG_PARTITION_PCT = 50.0


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


def long_notional_mult(long_partition_pct: float) -> float:
    return max(float(long_partition_pct), 1.0) / 100.0 * SHORT_LEVERAGE


def short_notional_mult(short1_pct: float, short2_pct: float) -> float:
    return (max(float(short1_pct), 0.0) + max(float(short2_pct), 0.0)) / 100.0 * LONG1_LEVERAGE


def sanitize_partitions(
    long_pct: float,
    short1_pct: float,
    short2_pct: float,
) -> tuple[float, float, float, bool]:
    """
    Force ~balanced hedge sizing. Returns (long, short1, short2, changed).
    Caps each recovery leg and total short notional vs long.
    """
    long_u = max(1.0, min(100.0, float(long_pct)))
    s1 = max(MIN_RECOVERY_LEG_PCT, min(MAX_RECOVERY_LEG_PCT, float(short1_pct)))
    s2 = max(MIN_RECOVERY_LEG_PCT, min(MAX_RECOVERY_LEG_PCT, float(short2_pct)))
    changed = (
        abs(s1 - float(short1_pct)) > 1e-9
        or abs(s2 - float(short2_pct)) > 1e-9
        or abs(long_u - float(long_pct)) > 1e-9
    )

    long_n = long_notional_mult(long_u)
    short_n = short_notional_mult(s1, s2)
    max_short_n = long_n * MAX_SHORT_VS_LONG_NOTIONAL
    if short_n > max_short_n + 1e-9 and short_n > 0:
        scale = max_short_n / short_n
        s1 = max(MIN_RECOVERY_LEG_PCT, min(MAX_RECOVERY_LEG_PCT, s1 * scale))
        s2 = max(MIN_RECOVERY_LEG_PCT, min(MAX_RECOVERY_LEG_PCT, s2 * scale))
        # If still over (min floors), snap to safe balanced defaults.
        if short_notional_mult(s1, s2) > max_short_n + 1e-9:
            s1 = SAFE_RECOVERY_LEG_PCT
            s2 = SAFE_RECOVERY_LEG_PCT
            long_u = SAFE_LONG_PARTITION_PCT
        changed = True

    # Explicit toxic legacy 40/40 → safe 12.5/12.5
    if float(short1_pct) >= 35.0 and float(short2_pct) >= 35.0:
        s1 = SAFE_RECOVERY_LEG_PCT
        s2 = SAFE_RECOVERY_LEG_PCT
        changed = True

    return long_u, round(s1, 4), round(s2, 4), changed


def is_toxic_legacy_sizing(long_pct: float, short1_pct: float, short2_pct: float) -> bool:
    if float(short1_pct) >= 35.0 and float(short2_pct) >= 35.0:
        return True
    long_n = long_notional_mult(long_pct)
    short_n = short_notional_mult(short1_pct, short2_pct)
    return long_n > 0 and short_n / long_n > MAX_SHORT_VS_LONG_NOTIONAL + 1e-9
