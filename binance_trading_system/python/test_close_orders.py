#!/usr/bin/env python3
"""Close order param tests — hedge mode must not send reduceOnly."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))

from binance_connector import BinanceConnector  # noqa: E402


class HedgeConnector(BinanceConnector):
    def __init__(self) -> None:
        self.cfg = SimpleNamespace(paper=False, api_key="k", api_secret="s", symbol="TACUSDT")
        self._hedge_mode = True

    def is_hedge_mode(self) -> bool:
        return True


class OneWayConnector(BinanceConnector):
    def __init__(self) -> None:
        self.cfg = SimpleNamespace(paper=False, api_key="k", api_secret="s", symbol="TACUSDT")
        self._hedge_mode = False

    def is_hedge_mode(self) -> bool:
        return False


def test_hedge_close_no_reduce_only() -> None:
    c = HedgeConnector()
    p = c._market_close_params(
        symbol="TACUSDT",
        side="BUY",
        quantity=100.0,
        client_order_id="test",
        hedge_position_side="SHORT",
    )
    assert "reduceOnly" not in p
    assert p["positionSide"] == "SHORT"
    print("OK hedge close uses positionSide only")


def test_oneway_close_has_reduce_only() -> None:
    c = OneWayConnector()
    p = c._market_close_params(
        symbol="TACUSDT",
        side="BUY",
        quantity=100.0,
        client_order_id="test",
        entry_side_for_reduce="SELL",
    )
    assert p.get("reduceOnly") == "true"
    assert "positionSide" not in p
    print("OK one-way close uses reduceOnly")


def test_hedge_tp_no_reduce_only() -> None:
    c = HedgeConnector()
    p = c._conditional_close_params(
        symbol="TACUSDT",
        exit_side="BUY",
        order_type="TAKE_PROFIT_MARKET",
        stop_price=1.0,
        quantity=10.0,
        client_order_id="tp",
        entry_side="SELL",
    )
    assert "reduceOnly" not in p
    assert p["positionSide"] == "SHORT"
    print("OK hedge TP uses positionSide only")


if __name__ == "__main__":
    test_hedge_close_no_reduce_only()
    test_oneway_close_has_reduce_only()
    test_hedge_tp_no_reduce_only()
    print("test_close_orders: ALL OK")
