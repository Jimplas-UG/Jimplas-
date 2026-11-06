#!/usr/bin/env python3
"""Regression locks for the Nov 2026 Sep/Oct audit. Behaviour only — no strategy knob changes.

  python test_audit_nov_fixes.py
"""
from __future__ import annotations

import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from binance_connector import PositionsUnavailable  # noqa: E402
from momentum_scanner import (  # noqa: E402
    MAGIC_LONG1,
    MAGIC_SHORT,
    LONG1_LEVERAGE,
    SHORT_LEVERAGE,
    STATUS_LONG1,
    STATUS_SHORT,
    STATUS_WATCHING,
    LegPosition,
    MomentumScanner,
)


class _Cfg:
    paper = False
    api_key = "k"
    testnet = True


class CoolConnector:
    """Book reads raise like a 418/429 cool; closes are recorded."""

    def __init__(self) -> None:
        self.cfg = _Cfg()
        self._connected = True
        self._leverage_fail_cache: dict = {}
        self.unavailable = True
        self.closed: list[str] = []

    def rest_cooling_left(self) -> float:
        return 0.0

    def _weight_pause_left(self) -> float:
        return 0.0

    def cached_positions(self):
        return []

    def _book(self):
        if self.unavailable:
            raise PositionsUnavailable("REST cooling (418) 900s — positions unconfirmed")
        return []

    def confirmed_positions(self, *a, **k):
        return self._book()

    def positions(self, *a, **k):
        return [{"symbol": "AUDUSDT", "volume": 1.0, "positionSide": "SHORT", "type": "SELL"}]

    def exchange_short_qty(self, *a, **k):
        self._book()
        return 1.0

    def exchange_long_qty(self, *a, **k):
        self._book()
        return 0.0

    def ensure_exchange_leverage(self, *a, **k):
        return True

    def close_position(self, symbol, volume=None):
        self.closed.append(symbol)
        return {"ok": True, "closed": [{"order": 1}], "note": "already_flat"}

    def invalidate_positions_cache(self):
        return None

    def symbol_spec(self, *a, **k):
        return {"stepSize": 0.001, "minQty": 0.001}


def _short_coin(sc: MomentumScanner, entry: float = 100.0):
    sc.load_symbols(["AUDUSDT"])
    coin = sc._coins["AUDUSDT"]
    coin.short = LegPosition("SELL", entry, 2.5, SHORT_LEVERAGE, MAGIC_SHORT, entry * 0.975)
    coin.short_trough_price = entry
    coin.status = STATUS_SHORT
    coin.short_opened_ms = int(time.time() * 1000) - 60_000
    return coin


def test_invalidation_still_fires_during_rest_cool() -> None:
    conn = CoolConnector()
    sc = MomentumScanner(conn, lambda: True)
    coin = _short_coin(sc)
    coin.price = 107.0  # +7% adverse, past the 6.5% circuit breaker
    sc._manage_positions(coin)
    assert conn.closed == ["AUDUSDT"], "INVALIDATION must not be skipped while the book is cooling"
    print("OK invalidation fires through REST cool")


def test_short_tp_still_fires_during_rest_cool() -> None:
    conn = CoolConnector()
    sc = MomentumScanner(conn, lambda: True)
    coin = _short_coin(sc)
    coin.price = 97.0  # past the -2.5% TP
    sc._manage_positions(coin)
    assert conn.closed == ["AUDUSDT"], "SHORT_TP must not be skipped while the book is cooling"
    print("OK short TP fires through REST cool")


def test_rescue_still_fires_during_rest_cool() -> None:
    conn = CoolConnector()
    sc = MomentumScanner(conn, lambda: True)
    coin = _short_coin(sc)
    coin.long1 = LegPosition("BUY", 102.0, 3.92, LONG1_LEVERAGE, MAGIC_LONG1, 104.55)
    coin.status = STATUS_LONG1
    coin.long1_opened_ms = int(time.time() * 1000) - 60_000
    coin.price = 106.4
    sc._manage_positions(coin)
    assert conn.closed == ["AUDUSDT"], "RESCUE must not be skipped while the book is cooling"
    print("OK rescue fires through REST cool")


def test_no_hedge_opens_on_unconfirmed_book() -> None:
    conn = CoolConnector()
    sc = MomentumScanner(conn, lambda: True)
    coin = _short_coin(sc)
    opened: list[str] = []
    sc._try_open_long1 = lambda c: opened.append(c.symbol)  # type: ignore[method-assign]
    coin.price = 102.5
    sc._manage_positions(coin)
    assert opened == [], "an unconfirmed book must not add a hedge"
    print("OK no hedge is added on an unconfirmed book")


def test_testnet_stream_volume_cannot_satisfy_the_floor() -> None:
    conn = CoolConnector()
    conn.unavailable = False
    sc = MomentumScanner(conn, lambda: True)
    sc.load_symbols(["AUDUSDT"])
    sc.apply_volume_map({"AUDUSDT": 2_000_000.0})
    sc.on_tick("AUDUSDT", 100.0, None, None, 400_000_000.0)
    coin = sc._coins["AUDUSDT"]
    assert coin.quote_vol_24h == 2_000_000.0, "inflated testnet tick volume must not replace mainnet"
    assert not sc._liquidity_ok(coin)
    print("OK testnet stream volume cannot satisfy the liquidity floor")


def test_market_orders_ask_for_the_real_fill() -> None:
    src = open(os.path.join(_HERE, "binance_connector.py"), encoding="utf-8").read()
    assert src.count('"newOrderRespType": "RESULT"') == 2, "open and close must both request fills"
    print("OK open and close orders request the real fill price")


def test_mainnet_scanner_uses_the_live_market_route() -> None:
    import scanner_stream

    assert scanner_stream.MAINNET_WS.endswith("/market/ws"), "legacy mainnet /ws delivers no miniTicker"
    print("OK mainnet scanner stream uses the /market route")


if __name__ == "__main__":
    test_invalidation_still_fires_during_rest_cool()
    test_short_tp_still_fires_during_rest_cool()
    test_rescue_still_fires_during_rest_cool()
    test_no_hedge_opens_on_unconfirmed_book()
    test_testnet_stream_volume_cannot_satisfy_the_floor()
    test_market_orders_ask_for_the_real_fill()
    test_mainnet_scanner_uses_the_live_market_route()
    print("test_audit_nov_fixes: ALL OK")
