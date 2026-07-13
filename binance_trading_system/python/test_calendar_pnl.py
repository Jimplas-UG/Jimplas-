"""Calendar PnL must ignore phantom income legs (raw Binance REALIZED_PNL hiccup)."""
from __future__ import annotations

from deal_pnl import is_phantom_pnl


def test_phantom_without_quote_detected() -> None:
    # No notional → absolute threshold
    assert is_phantom_pnl(-113805.2, qty=0, price=0, quote_qty=0)
    assert is_phantom_pnl(-113489.0, qty=113489.0, price=0.0, quote_qty=0.0)


def test_normal_desk_pnl_not_phantom() -> None:
    assert not is_phantom_pnl(-215.49, qty=1000.0, price=0.05, quote_qty=50.0)
    assert not is_phantom_pnl(12.5, qty=10.0, price=100.0, quote_qty=1000.0)


def test_max_leg_calendar_cap() -> None:
    """Desk calendar uses TRADE_PNL_MAX_LEG — XPIN-style ~113k income legs are dropped."""
    max_leg = 5000.0
    assert abs(-113805.2) > max_leg
    assert abs(-215.49) <= max_leg


if __name__ == "__main__":
    test_phantom_without_quote_detected()
    test_normal_desk_pnl_not_phantom()
    test_max_leg_calendar_cap()
    print("test_calendar_pnl: ALL OK")
