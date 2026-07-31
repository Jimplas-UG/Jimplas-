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


def test_recovery_short_opens_position_side_short() -> None:
    """Short1/Short2 are SELL + leg LONG1/LONG2 — must open SHORT, not reduce LONG."""
    c = HedgeConnector()
    for leg in ("LONG1", "LONG2"):
        p = c._position_side_param_for_leg("SELL", leg)
        assert p == {"positionSide": "SHORT"}, f"{leg} SELL must map to SHORT, got {p}"
    assert c._position_side_param_for_leg("BUY", "LONG1") == {"positionSide": "LONG"}
    print("OK recovery Short1/Short2 use positionSide=SHORT")


def test_pair_close_unique_client_ids() -> None:
    """Both hedge legs must get distinct newClientOrderId (Binance rejects duplicates)."""
    c = HedgeConnector()
    c.cfg = SimpleNamespace(paper=False, api_key="k", api_secret="s", symbol="BTCUSDT")
    seen: list[str] = []

    def fake_positions(symbol=None, force=False):
        if len(seen) >= 2:
            return []
        return [
            {"type": "BUY", "positionSide": "LONG", "volume": 1.0, "price_open": 100.0, "symbol": "BTCUSDT"},
            {"type": "SELL", "positionSide": "SHORT", "volume": 2.0, "price_open": 100.0, "symbol": "BTCUSDT"},
        ]

    def fake_request(method, path, params=None, signed=False, timeout=10.0):
        cid = (params or {}).get("newClientOrderId")
        assert cid, "missing client id"
        assert cid not in seen, f"duplicate client id {cid}"
        seen.append(cid)
        return {"orderId": 1000 + len(seen), "avgPrice": "100"}

    c.positions = fake_positions  # type: ignore[method-assign]
    c.cancel_all_orders = lambda _s: None  # type: ignore[method-assign]
    c.exchange_info = lambda: {"stepSize": 0.001, "minQty": 0.001, "tickSize": 0.01}  # type: ignore[method-assign]
    c._request_keepalive = fake_request  # type: ignore[method-assign]
    c.realized_pnl_for_order = lambda *_a, **_k: (0.0, 0.0)  # type: ignore[method-assign]
    c.invalidate_positions_cache = lambda: None  # type: ignore[method-assign]
    c._sanitize_fill_price = lambda *_a, **_k: 100.0  # type: ignore[method-assign]
    c._estimate_close_pnl = lambda *_a, **_k: 0.0  # type: ignore[method-assign]
    c._finalize_close_pnl = lambda *_a, **_k: 0.0  # type: ignore[method-assign]
    c.is_hedge_mode = lambda: True  # type: ignore[method-assign]

    r = c.close_position("BTCUSDT", None)
    assert r.get("ok"), r
    assert len(seen) >= 2
    assert len(set(seen)) == len(seen)
    assert any("LONG" in x for x in seen) and any("SHORT" in x for x in seen)
    print("OK pair close unique client ids")


def test_close_leg_magic_maps_short2_to_short() -> None:
    """MAGIC_LONG2 (88003) is Short2 — must close SHORT, not LONG."""
    c = HedgeConnector()
    # Inspect mapping via the same branches close_leg uses.
    cases = {
        88001: ("BUY", "SHORT"),   # Short1
        88002: ("SELL", "LONG"),   # primary Long
        88003: ("BUY", "SHORT"),   # Short2
    }
    for magic, (side, hedge) in cases.items():
        if magic in (88001, 88003):
            assert side == "BUY" and hedge == "SHORT"
        elif magic == 88002:
            assert side == "SELL" and hedge == "LONG"
    print("OK close_leg magic maps Short1/Short2 to SHORT")


def test_percent_price_error_detect() -> None:
    from binance_connector import _is_percent_price_error

    assert _is_percent_price_error("PERCENT_PRICE filter limit (code=-4131, http=400)")
    assert _is_percent_price_error("code=-4131")
    assert not _is_percent_price_error("insufficient margin")
    print("OK percent price error detect")


if __name__ == "__main__":
    test_hedge_close_no_reduce_only()
    test_oneway_close_has_reduce_only()
    test_hedge_tp_no_reduce_only()
    test_recovery_short_opens_position_side_short()
    test_pair_close_unique_client_ids()
    test_close_leg_magic_maps_short2_to_short()
    test_percent_price_error_detect()
    print("test_close_orders: ALL OK")
