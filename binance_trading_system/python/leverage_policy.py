"""
Fixed per-leg leverage — institutional policy, no overrides.

SHORT (and manual entries): 5x
LONG1 / LONG2 recovery legs: 10x
"""

from __future__ import annotations

SHORT_LEVERAGE = 5
LONG1_LEVERAGE = 10
LONG2_LEVERAGE = 10

ALLOWED_LEVERAGES = frozenset({SHORT_LEVERAGE, LONG1_LEVERAGE})


def required_leverage(leg: str, side: str = "") -> int | None:
    """Return mandated leverage for a trading leg, or None if not a policy leg."""
    leg_u = (leg or "").upper()
    side_u = side.upper()
    if leg_u == "SHORT":
        return SHORT_LEVERAGE
    if leg_u == "LONG1":
        return LONG1_LEVERAGE
    if leg_u == "LONG2":
        return LONG2_LEVERAGE
    if leg_u == "MANUAL" and side_u == "SELL":
        return SHORT_LEVERAGE
    return None


def apply_leverage_policy(leg: str, side: str, requested: int) -> int:
    """Force signal leverage to policy value; ignore env/UI overrides."""
    required = required_leverage(leg, side)
    if required is not None:
        return required
    return max(int(requested or SHORT_LEVERAGE), 1)
