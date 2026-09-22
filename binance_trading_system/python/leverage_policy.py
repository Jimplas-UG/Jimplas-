"""
Fixed per-leg leverage — institutional policy, no overrides.

Primary short (SHORT SELL): 5x sizing + Binance exchange leverage
Recovery longs (LONG1 / LONG2 BUY): 10x sizing + Binance exchange leverage
Manual desk order: 5x

Note: Binance USDT-M sets one leverage per symbol. While Long 1 / Long 2 are open the
symbol is at 10x (including the primary short). After the longs close, short-only
restores to 5x.
"""

from __future__ import annotations

SHORT_LEVERAGE = 5
LONG1_LEVERAGE = 10
LONG2_LEVERAGE = 10

ALLOWED_LEVERAGES = frozenset({SHORT_LEVERAGE, LONG1_LEVERAGE})


def sizing_leverage(leg: str, side: str = "") -> int | None:
    """Leverage for notional / margin math — primary short 5x, recovery longs 10x."""
    leg_u = (leg or "").upper()
    if leg_u == "MANUAL":
        return SHORT_LEVERAGE
    if leg_u == "SHORT":
        return SHORT_LEVERAGE
    if leg_u == "LONG1":
        return LONG1_LEVERAGE
    if leg_u == "LONG2":
        return LONG2_LEVERAGE
    return None


def required_leverage(leg: str, side: str = "") -> int | None:
    """Alias — sizing leverage for orders."""
    return sizing_leverage(leg, side)


def exchange_leverage(leg: str = "", side: str = "") -> int:
    """Leverage sent to Binance /fapi/v1/leverage — short 5x, recovery longs 10x."""
    required = sizing_leverage(leg, side)
    if required is not None:
        return required
    return SHORT_LEVERAGE


def policy_display_leverage(*, side: str, position_side: str = "") -> int:
    """UI/policy leverage: primary short 5x, recovery longs 10x."""
    ps = (position_side or "").upper()
    side_u = side.upper()
    if ps == "SHORT" or side_u == "SELL":
        return SHORT_LEVERAGE
    return LONG1_LEVERAGE


def symbol_exchange_leverage(*, has_recovery_long: bool) -> int:
    """Active symbol leverage on Binance while a strategy is open."""
    return LONG1_LEVERAGE if has_recovery_long else SHORT_LEVERAGE


def apply_leverage_policy(leg: str, side: str, requested: int) -> int:
    """Force signal sizing leverage to policy value; ignore env/UI overrides."""
    required = sizing_leverage(leg, side)
    if required is not None:
        return required
    return max(int(requested or SHORT_LEVERAGE), 1)
