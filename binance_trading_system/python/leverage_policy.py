"""
Fixed per-leg leverage — institutional policy, no overrides.

SHORT (manual entries): 5x exchange + sizing
Primary long (LONG1 BUY): 5x sizing
Recovery shorts (LONG1/LONG2 SELL): 10x sizing only (effective exposure), exchange stays 5x

Binance USDT-M shares one leverage per symbol in hedge mode — never call /leverage
with 10 while a short leg is live or the short inherits 10x.
"""

from __future__ import annotations

SHORT_LEVERAGE = 5
LONG1_LEVERAGE = 10
LONG2_LEVERAGE = 10

ALLOWED_LEVERAGES = frozenset({SHORT_LEVERAGE, LONG1_LEVERAGE})


def sizing_leverage(leg: str, side: str = "") -> int | None:
    """Leverage for notional / margin math — primary long 5x, recovery shorts 10x."""
    leg_u = (leg or "").upper()
    side_u = side.upper()
    if leg_u == "SHORT":
        return SHORT_LEVERAGE
    if leg_u == "LONG1":
        return SHORT_LEVERAGE if side_u == "BUY" else LONG1_LEVERAGE
    if leg_u == "LONG2":
        return LONG2_LEVERAGE
    if leg_u == "MANUAL" and side_u == "SELL":
        return SHORT_LEVERAGE
    return None


def required_leverage(leg: str, side: str = "") -> int | None:
    """Alias — sizing leverage for orders."""
    return sizing_leverage(leg, side)


def exchange_leverage(leg: str = "") -> int:
    """Leverage sent to Binance /fapi/v1/leverage — always 5x for every leg."""
    return SHORT_LEVERAGE


def policy_display_leverage(*, side: str, position_side: str = "") -> int:
    """UI/policy leverage per open leg (short 5x, hedge longs 10x effective)."""
    ps = (position_side or "").upper()
    side_u = side.upper()
    if ps == "LONG" or (side_u == "BUY" and ps != "SHORT"):
        return LONG1_LEVERAGE
    return SHORT_LEVERAGE


def apply_leverage_policy(leg: str, side: str, requested: int) -> int:
    """Force signal sizing leverage to policy value; ignore env/UI overrides."""
    required = sizing_leverage(leg, side)
    if required is not None:
        return required
    return max(int(requested or SHORT_LEVERAGE), 1)
