#!/usr/bin/env python3
"""Tests for deal P&L sanitization (phantom -$113k on XPIN-style fills)."""
from deal_pnl import (
    effective_fill_price,
    is_phantom_pnl,
    normalize_user_trades,
)


def test_effective_price_from_quote_qty() -> None:
    p = effective_fill_price(113739.0, 1.0, 249.2)
    assert abs(p - 0.002191) < 1e-5
    print("OK effective price from quoteQty")


def test_phantom_pnl_detected() -> None:
    assert is_phantom_pnl(-113489.80, 113739.0, 1.0, 249.2)
    assert not is_phantom_pnl(2.81, 112663.0, 0.002193, 247.0)
    print("OK phantom pnl detection")


def test_xpin_pair_recompute() -> None:
    trades = [
        {
            "symbol": "XPINUSDT",
            "type": "SELL",
            "volume": 113739.0,
            "price": 0.002191,
            "quote_qty": 249.2,
            "profit": 0.0,
            "position_side": "SHORT",
            "time": 1000,
            "ticket": 1,
        },
        {
            "symbol": "XPINUSDT",
            "type": "BUY",
            "volume": 113739.0,
            "price": 1.0,
            "quote_qty": 249.2,
            "profit": -113489.797851,
            "position_side": "SHORT",
            "time": 2000,
            "ticket": 2,
        },
    ]
    out = normalize_user_trades(trades)
    close = [r for r in out if r["type"] == "BUY"][0]
    assert close["pnl_corrected"] is True
    assert abs(close["price"] - 0.002191) < 1e-5
    assert abs(close["profit"]) < 1.0
    print("OK xpin phantom loss recomputed to ~flat")


def test_xpin_bad_quote_qty_equals_qty() -> None:
    trades = [
        {
            "symbol": "XPINUSDT",
            "type": "SELL",
            "volume": 113739.0,
            "price": 0.002191,
            "quote_qty": 249.2,
            "profit": 0.0,
            "position_side": "SHORT",
            "time": 1000,
        },
        {
            "symbol": "XPINUSDT",
            "type": "BUY",
            "volume": 113739.0,
            "price": 1.0,
            "quote_qty": 113739.0,
            "profit": -113489.797851,
            "position_side": "SHORT",
            "time": 2000,
        },
    ]
    out = normalize_user_trades(trades)
    close = [r for r in out if r["type"] == "BUY"][0]
    assert close["pnl_corrected"] is True
    assert abs(close["profit"]) < 1.0
    print("OK bad quoteQty=qty handled")


def test_normal_close_unchanged() -> None:
    trades = [
        {
            "symbol": "XPINUSDT",
            "type": "SELL",
            "volume": 112663.0,
            "price": 0.002218,
            "quote_qty": 249.7,
            "profit": 0.0,
            "position_side": "SHORT",
            "time": 1000,
        },
        {
            "symbol": "XPINUSDT",
            "type": "BUY",
            "volume": 112663.0,
            "price": 0.002193,
            "quote_qty": 247.0,
            "profit": 2.816575,
            "position_side": "SHORT",
            "time": 2000,
        },
    ]
    out = normalize_user_trades(trades)
    close = [r for r in out if r["type"] == "BUY"][0]
    assert abs(close["profit"] - 2.816575) < 1e-4
    assert "pnl_corrected" not in close
    print("OK normal close unchanged")


def main() -> None:
    test_effective_price_from_quote_qty()
    test_phantom_pnl_detected()
    test_xpin_pair_recompute()
    test_xpin_bad_quote_qty_equals_qty()
    test_normal_close_unchanged()
    print("test_deal_pnl: ALL OK")


if __name__ == "__main__":
    main()
