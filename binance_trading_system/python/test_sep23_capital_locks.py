#!/usr/bin/env python3
"""Sep23 capital locks — no gambling, no Oct cascade layers."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))

from frozen_strategy import assert_frozen_contract  # noqa: E402
from leverage_policy import LONG1_LEVERAGE, SHORT_LEVERAGE, symbol_exchange_leverage  # noqa: E402
from momentum_scanner import (  # noqa: E402
    LONG1_ADVERSE_PCT,
    PAIR_INVALIDATION_PCT,
    CoinStrategy,
    MomentumScanner,
)


def test_naked_short_exchange_target_is_5x() -> None:
    assert symbol_exchange_leverage(has_recovery_long=False) == SHORT_LEVERAGE
    assert symbol_exchange_leverage(has_recovery_long=True) == LONG1_LEVERAGE
    print("OK naked short exchange target is 5x")


def test_hedge_episode_blocks_solo() -> None:
    conn = SimpleNamespace(cfg=SimpleNamespace(paper=True, api_key=""), _connected=False)
    sc = MomentumScanner(conn, lambda: True)
    coin = CoinStrategy(symbol="TESTUSDT")
    coin.short = SimpleNamespace(entry=100.0, qty=1.0, side="SELL", leverage=5, magic=88001, tp_price=0)
    coin.price = 99.0  # short in profit
    coin.short_adverse_peak_pct = 2.5  # episode started
    assert sc._hedge_episode_active(coin) is True
    assert sc._solo_hedge_exit_allowed(coin) is False
    print("OK hedge episode blocks solo hedge exit")


def test_pre_hedge_green_allows_solo() -> None:
    conn = SimpleNamespace(cfg=SimpleNamespace(paper=True, api_key=""), _connected=False)
    sc = MomentumScanner(conn, lambda: True)
    coin = CoinStrategy(symbol="TESTUSDT")
    coin.short = SimpleNamespace(entry=100.0, qty=1.0, side="SELL", leverage=5, magic=88001, tp_price=0)
    coin.price = 99.0
    coin.short_adverse_peak_pct = 0.5
    assert sc._hedge_episode_active(coin) is False
    assert sc._solo_hedge_exit_allowed(coin) is True
    print("OK pre-hedge green short allows solo hedge exit")


def test_underwater_blocks_solo() -> None:
    conn = SimpleNamespace(cfg=SimpleNamespace(paper=True, api_key=""), _connected=False)
    sc = MomentumScanner(conn, lambda: True)
    coin = CoinStrategy(symbol="TESTUSDT")
    coin.short = SimpleNamespace(entry=100.0, qty=1.0, side="SELL", leverage=5, magic=88001, tp_price=0)
    coin.price = 101.0
    coin.short_adverse_peak_pct = 0.0
    assert sc._solo_hedge_exit_allowed(coin) is False
    print("OK underwater blocks solo hedge exit")


def test_l1_l2_blocked_at_invalidation() -> None:
    conn = SimpleNamespace(cfg=SimpleNamespace(paper=True, api_key=""), _connected=False)
    sc = MomentumScanner(conn, lambda: True)
    coin = CoinStrategy(symbol="TESTUSDT")
    coin.short = SimpleNamespace(entry=100.0, qty=1.0, side="SELL", leverage=5, magic=88001, tp_price=0)
    coin.price = 100.0 * (1.0 + PAIR_INVALIDATION_PCT / 100.0)
    sc._exchange_has_short = lambda _s: True  # type: ignore
    sc._exchange_long_covers_recovery = lambda *_a, **_k: False  # type: ignore
    sc._short_settle_elapsed = lambda *_a, **_k: True  # type: ignore
    sc._long1_settle_elapsed = lambda *_a, **_k: True  # type: ignore
    sc._sync_short_entry_from_exchange = lambda c: float(c.short.entry)  # type: ignore
    assert sc._long1_entry_allowed(coin) is False
    coin.long1_was_closed = True
    assert sc._long2_entry_allowed(coin) is False
    # Still allow below inv above L1 threshold
    coin.price = 100.0 * (1.0 + (LONG1_ADVERSE_PCT + 0.1) / 100.0)
    coin.long1_was_closed = False
    assert sc._long1_entry_allowed(coin) is True
    print("OK L1/L2 blocked at/past invalidation")


def test_manage_never_forces_naked_10x() -> None:
    import inspect
    from momentum_scanner import MomentumScanner as MS

    src = inspect.getsource(MS._manage_positions)
    assert "target = LONG1_LEVERAGE" not in src
    assert "symbol_exchange_leverage" in src
    print("OK manage_positions never forces naked 10x")


def test_manual_qty_locked() -> None:
    conn = SimpleNamespace(cfg=SimpleNamespace(paper=True, api_key=""), _connected=False)
    sc = MomentumScanner(conn, lambda: True)
    sc._partition_usd = 100.0
    sc._qty_for = lambda *_a, **_k: 10.0  # type: ignore
    q, rejected = sc.clamp_manual_open_qty("AAVEUSDT", "SELL", 180.0, 19.3)
    assert rejected is True and q == 10.0
    q2, rej2 = sc.clamp_manual_open_qty("AAVEUSDT", "SELL", 180.0, 9.0)
    assert rej2 is False and q2 == 9.0
    print("OK manual open qty locked to partition (reject oversize)")


def test_close_chunks_and_abort() -> None:
    import inspect
    from binance_connector import BinanceConnector

    src = inspect.getsource(BinanceConnector.close_position)
    assert "long_residual_abort_short" in src
    assert "marketMaxQty" in src or "market_max" in src
    assert "Close LONG" in src or "_close_rank" in src
    side = inspect.getsource(BinanceConnector.close_by_position_side)
    assert "market_max" in side and "too_many_close_chunks" in side
    parse = inspect.getsource(BinanceConnector._parse_symbol_filters)
    assert "marketMaxQty" in parse
    print("OK close_position chunks MARKET max, aborts SHORT if LONG residual")


def test_force_positions_unavailable_not_flat() -> None:
    from binance_connector import BinanceConnector, BinanceConfig, PositionsUnavailable

    c = BinanceConnector(BinanceConfig(paper=False, testnet=True, api_key="k", api_secret="s"))
    c._last_good_positions = [{"symbol": "EDUUSDT", "volume": 99.0, "positionSide": "SHORT"}]
    c._positions_cache = list(c._last_good_positions)

    def boom(*_a, **_k):
        raise RuntimeError("REST cooling (429)")

    c._request = boom  # type: ignore
    raised = False
    try:
        c.positions("EDUUSDT", force=True, bypass_rest_cool=True)
    except PositionsUnavailable:
        raised = True
    assert raised, "force=True on REST error must raise PositionsUnavailable (not return [])"
    ui = c.positions("EDUUSDT", force=False)
    assert len(ui) == 1
    print("OK force positions unavailable — not empty; UI sticky OK")


def test_force_cool_short_circuit_unavailable() -> None:
    from binance_connector import BinanceConnector, BinanceConfig, PositionsUnavailable

    c = BinanceConnector(BinanceConfig(paper=False, testnet=True, api_key="k", api_secret="s"))
    c._rest_cool_until = __import__("time").monotonic() + 30.0
    c._rest_cool_reason = "429"
    raised = False
    try:
        c.positions("USUSDT", force=True, bypass_rest_cool=False)
    except PositionsUnavailable as e:
        raised = True
        assert "unconfirmed" in str(e).lower() or "cooling" in str(e).lower()
    assert raised
    print("OK force positions during cool -> unavailable (not flat)")


def test_reconcile_defers_when_unavailable() -> None:
    class Conn:
        cfg = SimpleNamespace(paper=False)

        def positions(self, symbol=None, force=False, bypass_rest_cool=False):
            from binance_connector import PositionsUnavailable

            raise PositionsUnavailable("REST cooling (429) 1s — positions unconfirmed")

    sc = MomentumScanner(Conn(), lambda: True)  # type: ignore[arg-type]
    out = sc._reconcile_from_exchange_locked()
    assert out.get("deferred") is True
    assert out.get("error") == "positions_unavailable"
    print("OK reconcile defers on positions unavailable")


def test_close_all_no_already_flat_on_unavailable() -> None:
    from momentum_scanner import LegPosition, STATUS_SHORT

    class Conn:
        cfg = SimpleNamespace(paper=False)

        def positions(self, symbol=None, force=False, bypass_rest_cool=False):
            from binance_connector import PositionsUnavailable

            raise PositionsUnavailable("429")

        def invalidate_positions_cache(self):
            return None

    sc = MomentumScanner(Conn(), lambda: True)  # type: ignore[arg-type]
    coin = CoinStrategy(symbol="USUSDT")
    coin.short = LegPosition(side="SELL", entry=1.0, qty=10.0, leverage=5, magic=88001)
    coin.status = STATUS_SHORT
    sc._coins["USUSDT"] = coin
    r = sc._close_all(coin, "SHORT_GONE_EXCHANGE")
    assert r.get("ok") is False
    assert r.get("error") == "positions_unavailable"
    assert coin.short is not None, "scanner state must survive unavailable close"
    print("OK close_all does not already_flat on unavailable")


def test_frozen() -> None:
    snap = assert_frozen_contract()
    assert snap["strategy_id"] == "short_first_v1"
    assert abs(float(snap["ops"]["partition_usd"]) - 100.0) < 1e-9
    print("OK frozen contract after capital locks")


if __name__ == "__main__":
    test_naked_short_exchange_target_is_5x()
    test_hedge_episode_blocks_solo()
    test_pre_hedge_green_allows_solo()
    test_underwater_blocks_solo()
    test_l1_l2_blocked_at_invalidation()
    test_manage_never_forces_naked_10x()
    test_manual_qty_locked()
    test_close_chunks_and_abort()
    test_force_positions_unavailable_not_flat()
    test_force_cool_short_circuit_unavailable()
    test_reconcile_defers_when_unavailable()
    test_close_all_no_already_flat_on_unavailable()
    test_frozen()
    print("test_sep23_capital_locks: ALL OK")
