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


def test_recovery_long_opens_position_side_long() -> None:
    """Long1/Long2 are BUY recovery hedges — must open LONG, not reduce the primary SHORT."""
    c = HedgeConnector()
    for leg in ("LONG1", "LONG2"):
        p = c._position_side_param_for_leg("BUY", leg)
        assert p == {"positionSide": "LONG"}, f"{leg} BUY must map to LONG, got {p}"
    assert c._position_side_param_for_leg("SELL", "SHORT") == {"positionSide": "SHORT"}
    print("OK recovery Long1/Long2 use positionSide=LONG")


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


def test_close_leg_magic_maps_recovery_longs_to_long() -> None:
    """MAGIC_LONG1/LONG2 (88002/88003) are recovery longs — must close LONG, not SHORT."""
    from binance_connector import close_leg_sides

    assert close_leg_sides(88001) == ("BUY", "SHORT"), "primary short closes the SHORT side"
    assert close_leg_sides(88002) == ("SELL", "LONG"), "Long 1 closes the LONG side"
    assert close_leg_sides(88003) == ("SELL", "LONG"), "Long 2 closes the LONG side"
    assert close_leg_sides(12345) is None, "unknown magic falls back to a full close"
    print("OK close_leg magic maps Long1/Long2 to LONG")


def test_percent_price_error_detect() -> None:
    from binance_connector import _is_percent_price_error

    assert _is_percent_price_error("PERCENT_PRICE filter limit (code=-4131, http=400)")
    assert _is_percent_price_error("code=-4131")
    assert not _is_percent_price_error("insufficient margin")
    print("OK percent price error detect")


def test_price_bound_error_detect() -> None:
    from binance_connector import _is_price_bound_error

    assert _is_price_bound_error("Limit price can't be higher than 0.0521 (code=-4016, http=400)")
    assert _is_price_bound_error("Limit price can't be lower than 1.23")
    assert _is_price_bound_error("code=-4016")
    assert not _is_price_bound_error("code=-4131 PERCENT_PRICE")
    assert not _is_price_bound_error("insufficient margin")
    print("OK price bound (-4016) error detect")


def test_buy_candidates_never_exceed_band_max() -> None:
    """Closing a SHORT (BUY) must never price above mark*multiplierUp — the -4016 cause."""
    from binance_connector import build_limit_ioc_candidates

    mark = 100.0
    # Ask far above the band after a violent dump/spike — old walk went to ask*1.10.
    prices, band_min, band_max = build_limit_ioc_candidates(
        exit_side="BUY",
        bid=99.0,
        ask=140.0,
        mark=mark,
        tick=0.01,
        multiplier_up=1.05,
        multiplier_down=0.95,
    )
    assert prices, "BUY walk must produce candidates"
    assert abs(band_max - 105.0) < 1e-9 and abs(band_min - 95.0) < 1e-9
    for px in prices:
        assert px <= band_max + 1e-12, f"{px} above band max {band_max}"
        assert px >= band_min - 1e-12, f"{px} below band min {band_min}"
    assert max(prices) <= mark * 1.05
    print("OK limit_ioc BUY candidates stay inside mark*multiplierUp")


def test_sell_candidates_never_below_band_min() -> None:
    from binance_connector import build_limit_ioc_candidates

    prices, band_min, band_max = build_limit_ioc_candidates(
        exit_side="SELL",
        bid=60.0,
        ask=61.0,
        mark=100.0,
        tick=0.01,
    )
    assert prices
    assert abs(band_min - 95.0) < 1e-9 and abs(band_max - 105.0) < 1e-9
    for px in prices:
        assert band_min - 1e-12 <= px <= band_max + 1e-12, f"{px} outside band"
    print("OK limit_ioc SELL candidates stay above mark*multiplierDown")


def test_default_band_when_multipliers_unknown() -> None:
    from binance_connector import build_limit_ioc_candidates

    prices, band_min, band_max = build_limit_ioc_candidates(
        exit_side="BUY", bid=9.9, ask=10.0, mark=10.0, tick=0.001,
        multiplier_up=None, multiplier_down=None,
    )
    assert abs(band_max - 10.5) < 1e-9, "default multiplierUp is 1.05"
    assert abs(band_min - 9.5) < 1e-9, "default multiplierDown is 0.95"
    assert prices and max(prices) <= band_max
    print("OK limit_ioc falls back to a 5% band when filters are unknown")


def test_limit_ioc_retries_lower_after_4016() -> None:
    """-4016 must drop the walk to a band-legal price instead of aborting the close."""
    c = HedgeConnector()
    c.cfg = SimpleNamespace(paper=False, api_key="k", api_secret="s", symbol="BANKUSDT")
    tried: list[float] = []
    max_allowed = 104.0  # exchange band ceiling for this side

    def fake_request(method, path, params=None, signed=False, timeout=10.0):
        px = float((params or {})["price"])
        tried.append(px)
        if px > max_allowed:
            raise RuntimeError(
                f"Limit price can't be higher than {max_allowed} (code=-4016, http=400)"
            )
        return {"orderId": 7, "status": "FILLED", "executedQty": params["quantity"], "avgPrice": px}

    c.get_symbol_spec = lambda _s: {  # type: ignore[method-assign]
        "tickSize": 0.01,
        "stepSize": 0.001,
        "minQty": 0.001,
        "multiplierUp": 1.10,
        "multiplierDown": 0.90,
    }
    c.book_ticker = lambda _s=None: {"bid": 105.0, "ask": 106.0}  # type: ignore[method-assign]
    c.mark_price = lambda _s=None: 100.0  # type: ignore[method-assign]
    c._request_keepalive = fake_request  # type: ignore[method-assign]
    c.realized_pnl_for_order = lambda *_a, **_k: (0.0, 0.0)  # type: ignore[method-assign]
    c.invalidate_positions_cache = lambda: None  # type: ignore[method-assign]
    c._estimate_close_pnl = lambda *_a, **_k: 0.0  # type: ignore[method-assign]

    r = c._limit_ioc_close_leg(
        symbol="BANKUSDT",
        exit_side="BUY",
        quantity=10.0,
        hedge_side="SHORT",
        entry_price=100.0,
    )
    assert r.get("ok"), r
    assert len(tried) >= 2, "walk must retry after -4016"
    assert tried[-1] <= max_allowed, f"final price {tried[-1]} still above the band"
    assert all(px <= 110.0 for px in tried), "no attempt may exceed mark*multiplierUp"
    print("OK limit_ioc walks down to a legal price after -4016")


def test_limit_ioc_second_pass_is_mark_centered() -> None:
    """First (book-anchored) pass unfilled -> refresh book/mark and retry mark-centered."""
    c = HedgeConnector()
    c.cfg = SimpleNamespace(paper=False, api_key="k", api_secret="s", symbol="BANKUSDT")
    books = [{"bid": 98.0, "ask": 99.0}, {"bid": 100.0, "ask": 100.5}]
    marks = [100.0, 100.2]
    calls = {"book": 0, "mark": 0, "orders": 0}

    def next_book(_s=None):
        i = min(calls["book"], len(books) - 1)
        calls["book"] += 1
        return books[i]

    def next_mark(_s=None):
        i = min(calls["mark"], len(marks) - 1)
        calls["mark"] += 1
        return marks[i]

    def fake_request(method, path, params=None, signed=False, timeout=10.0):
        calls["orders"] += 1
        if calls["book"] < 2:
            return {"orderId": 1, "status": "EXPIRED", "executedQty": 0}
        return {"orderId": 2, "status": "FILLED", "executedQty": params["quantity"], "avgPrice": params["price"]}

    c.get_symbol_spec = lambda _s: {"tickSize": 0.01, "stepSize": 0.001, "minQty": 0.001}  # type: ignore[method-assign]
    c.book_ticker = next_book  # type: ignore[method-assign]
    c.mark_price = next_mark  # type: ignore[method-assign]
    c._request_keepalive = fake_request  # type: ignore[method-assign]
    c.realized_pnl_for_order = lambda *_a, **_k: (0.0, 0.0)  # type: ignore[method-assign]
    c.invalidate_positions_cache = lambda: None  # type: ignore[method-assign]
    c._estimate_close_pnl = lambda *_a, **_k: 0.0  # type: ignore[method-assign]

    r = c._limit_ioc_close_leg(
        symbol="BANKUSDT", exit_side="BUY", quantity=5.0, hedge_side="SHORT", entry_price=100.0
    )
    assert r.get("ok"), r
    assert r.get("limit_ioc_pass") == 2, r
    assert calls["book"] == 2 and calls["mark"] == 2, "second pass must refresh book + mark"
    print("OK limit_ioc second pass refreshes book/mark and fills")


def test_symbol_filters_carry_price_band_multipliers() -> None:
    from binance_connector import BinanceConnector

    c = HedgeConnector()
    parsed = BinanceConnector._parse_symbol_filters(
        c,
        {
            "symbol": "BANKUSDT",
            "pricePrecision": 5,
            "filters": [
                {"filterType": "PRICE_FILTER", "tickSize": "0.00001"},
                {"filterType": "LOT_SIZE", "stepSize": "1", "minQty": "1", "maxQty": "100000"},
                {"filterType": "PERCENT_PRICE", "multiplierUp": "1.0500", "multiplierDown": "0.9500"},
            ],
        },
    )
    assert parsed["multiplierUp"] == 1.05
    assert parsed["multiplierDown"] == 0.95
    print("OK symbol filters expose PERCENT_PRICE multipliers")


if __name__ == "__main__":
    test_hedge_close_no_reduce_only()
    test_oneway_close_has_reduce_only()
    test_hedge_tp_no_reduce_only()
    test_recovery_long_opens_position_side_long()
    test_pair_close_unique_client_ids()
    test_close_leg_magic_maps_recovery_longs_to_long()
    test_percent_price_error_detect()
    test_price_bound_error_detect()
    test_buy_candidates_never_exceed_band_max()
    test_sell_candidates_never_below_band_min()
    test_default_band_when_multipliers_unknown()
    test_limit_ioc_retries_lower_after_4016()
    test_limit_ioc_second_pass_is_mark_centered()
    test_symbol_filters_carry_price_band_multipliers()
    print("test_close_orders: ALL OK")
