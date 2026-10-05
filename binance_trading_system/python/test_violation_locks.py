#!/usr/bin/env python3
"""Hard locks: naked short 5x, paired hold after hedge episode, no overlapping adopt."""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("SCANNER_EXEC", "1")
os.environ.setdefault("SCANNER_LONG_DELAY_MS", "0")

import momentum_scanner as ms
from leverage_policy import SHORT_LEVERAGE, symbol_exchange_leverage
from momentum_scanner import (
    LONG1_ADVERSE_PCT,
    MAGIC_SHORT,
    PAIR_INVALIDATION_PCT,
    SHORT_LEVERAGE as SCAN_SHORT_LEV,
    STATUS_SHORT,
    CoinStrategy,
    LegPosition,
    MomentumScanner,
)


def _scanner() -> MomentumScanner:
    conn = SimpleNamespace(
        cfg=SimpleNamespace(paper=True, api_key=""),
        _connected=True,
        ensure_exchange_leverage=lambda *_a, **_k: True,
    )
    return MomentumScanner(conn, lambda: True)


def test_naked_short_exchange_target_is_5x() -> None:
    assert symbol_exchange_leverage(has_recovery_long=False) == 5
    assert symbol_exchange_leverage(has_recovery_long=True) == 10
    assert SHORT_LEVERAGE == 5
    print("OK naked short exchange target is 5x")


def test_hedge_episode_blocks_solo_exit() -> None:
    sc = _scanner()
    coin = CoinStrategy(symbol="TESTUSDT")
    coin.short = LegPosition("SELL", 100.0, 1.0, SCAN_SHORT_LEV, MAGIC_SHORT, 97.5)
    coin.status = STATUS_SHORT
    coin.price = 99.0  # short in profit
    coin.short_adverse_peak_pct = LONG1_ADVERSE_PCT  # was in hedge territory
    assert sc._hedge_episode_active(coin) is True
    assert sc._solo_hedge_exit_allowed(coin) is False
    coin.long1 = LegPosition("BUY", 102.0, 1.0, 10, 88002, None)
    coin.short_adverse_peak_pct = 0.0
    assert sc._solo_hedge_exit_allowed(coin) is False
    print("OK hedge episode blocks solo hedge exit")


def test_pre_hedge_green_allows_solo() -> None:
    sc = _scanner()
    coin = CoinStrategy(symbol="TESTUSDT")
    coin.short = LegPosition("SELL", 100.0, 1.0, SCAN_SHORT_LEV, MAGIC_SHORT, 97.5)
    coin.price = 99.0
    coin.short_adverse_peak_pct = 0.5  # never hit +2%
    assert sc._hedge_episode_active(coin) is False
    assert sc._solo_hedge_exit_allowed(coin) is True
    print("OK pre-hedge green short allows solo hedge exit")


def test_underwater_blocks_solo() -> None:
    sc = _scanner()
    coin = CoinStrategy(symbol="TESTUSDT")
    coin.short = LegPosition("SELL", 100.0, 1.0, SCAN_SHORT_LEV, MAGIC_SHORT, 97.5)
    coin.price = 101.0
    coin.short_adverse_peak_pct = 0.0
    assert sc._short_underwater(coin) is True
    assert sc._solo_hedge_exit_allowed(coin) is False
    print("OK underwater blocks solo hedge exit")


def test_no_hedge_at_or_past_invalidation() -> None:
    sc = _scanner()
    coin = CoinStrategy(symbol="TESTUSDT")
    coin.short = LegPosition("SELL", 100.0, 1.0, SCAN_SHORT_LEV, MAGIC_SHORT, 97.5)
    coin.price = 100.0 * (1.0 + PAIR_INVALIDATION_PCT / 100.0)
    coin.short_adverse_peak_pct = PAIR_INVALIDATION_PCT
    # Fake exchange short present
    sc._exchange_has_short = lambda _s: True  # type: ignore
    sc._exchange_long_covers_recovery = lambda *_a, **_k: False  # type: ignore
    sc._short_settle_elapsed = lambda _c: True  # type: ignore
    sc._long1_settle_elapsed = lambda _c: True  # type: ignore
    assert sc._long1_entry_allowed(coin) is False
    coin.long1_was_closed = True
    assert sc._long2_entry_allowed(coin) is False
    print("OK L1/L2 blocked at/past invalidation")


def test_adopt_refreshes_without_overlap_flag() -> None:
    import inspect

    src = inspect.getsource(MomentumScanner._adopt_exchange_short)
    assert "already" in src
    assert "SHORT_LEVERAGE" in src
    print("OK adopt short refreshes in place (no overlap)")


def test_manage_never_forces_naked_10x() -> None:
    import inspect

    src = inspect.getsource(MomentumScanner._manage_positions)
    assert "target = LONG1_LEVERAGE" not in src
    assert "symbol_exchange_leverage(has_recovery_long=has_long)" in src
    print("OK manage_positions never forces naked 10x")


def test_manual_open_qty_locked_to_partition() -> None:
    sc = _scanner()
    sc._partition_usd = 100.0
    # At $100, short 50%@5x → notional $250 → qty=2.5 at px=100
    max_short = sc.max_manual_open_qty("TESTUSDT", "SELL", 100.0)
    assert 2.0 <= max_short <= 3.0, max_short
    qty, rejected = sc.clamp_manual_open_qty("TESTUSDT", "SELL", 100.0, 100.0)  # AAVE-sized bomb
    assert rejected is True
    assert qty == max_short
    qty2, rejected2 = sc.clamp_manual_open_qty("TESTUSDT", "SELL", 100.0, max_short)
    assert rejected2 is False
    # BUY recovery leg 40%@10x → notional $400 → qty=4 at px=100
    max_buy = sc.max_manual_open_qty("TESTUSDT", "BUY", 100.0)
    assert 3.5 <= max_buy <= 4.5, max_buy
    print("OK manual open qty locked to partition (reject oversize)")


def test_market_max_qty_clamped() -> None:
    from binance_connector import BinanceConnector

    info = {
        "stepSize": 1.0,
        "minQty": 1.0,
        "maxQty": 10_000_000.0,
        "marketMaxQty": 100_000.0,
        "marketMinQty": 1.0,
        "marketStepSize": 1.0,
        "minNotional": 5.0,
    }
    qty, err = BinanceConnector._validate_order_qty(BinanceConnector.__new__(BinanceConnector), 140056.0, 0.0028, info)
    assert err is None, err
    assert qty <= 100_000.0, qty
    assert qty >= 99_000.0, qty
    print("OK market max qty clamped (BEAMX -4005 lock)")


def test_short_entry_sync_never_deflates() -> None:
    sc = _scanner()
    sc._connector.cfg.paper = False  # exercise exchange sync path
    coin = CoinStrategy(symbol="AINUSDT")
    coin.short = LegPosition("SELL", 0.04865, 1.0, SCAN_SHORT_LEV, MAGIC_SHORT, 0.047)
    # Exchange reports a lower entry — must NOT deflate (would arm L1 early).
    sc._exchange_short_leg = lambda _s: {"price_open": 0.0475}  # type: ignore
    entry = sc._sync_short_entry_from_exchange(coin)
    assert abs(entry - 0.04865) < 1e-9, entry
    coin.price = 0.04912  # +0.97% vs real fill — must NOT pass 2% gate
    assert sc._short_adverse_pct(coin) < LONG1_ADVERSE_PCT
    # Higher exchange entry is allowed (more conservative).
    coin.short.entry = 0.04865
    sc._exchange_short_leg = lambda _s: {"price_open": 0.0490}  # type: ignore
    entry2 = sc._sync_short_entry_from_exchange(coin)
    assert abs(entry2 - 0.0490) < 1e-9, entry2
    print("OK short entry sync never deflates (no early L1/L2)")


def test_close_chunks_market_max_and_longs_first() -> None:
    import inspect
    from binance_connector import BinanceConnector

    src = inspect.getsource(BinanceConnector.close_position)
    assert "marketMaxQty" in src or "max_cell" in src
    assert "_close_rank" in src
    assert "long_residual_abort_short" in src
    assert "chunk" in src.lower()
    side = inspect.getsource(BinanceConnector.close_by_position_side)
    assert "max_cell" in side or "marketMaxQty" in side
    leg = inspect.getsource(BinanceConnector.close_leg)
    assert "close_by_position_side" in leg
    assert "_persistent_escape_4131_close" in src
    assert "_persistent_escape_4131_close" in side
    print("OK close_position chunks MARKET max, aborts SHORT if LONG residual, side/leg chunked")


def test_force_flat_4131_retries_until_fill() -> None:
    """MARKET -4131 must not give up after one expired IOC walk."""
    from binance_connector import BinanceConnector

    c = BinanceConnector()
    c.cfg.api_key = "k"
    c.cfg.api_secret = "s"
    c.cfg.paper = False
    calls = {"market": 0, "ioc": 0}

    def fake_market(**kwargs):
        return {
            "symbol": kwargs["symbol"],
            "side": kwargs["side"],
            "type": "MARKET",
            "quantity": kwargs["quantity"],
            "newClientOrderId": kwargs["client_order_id"],
            "positionSide": kwargs.get("hedge_position_side") or "SHORT",
        }

    c._market_close_params = fake_market  # type: ignore

    def fake_req(method, path, params=None, signed=False, timeout=10.0, bypass_rest_cool=False):
        if method == "POST" and (params or {}).get("type") == "MARKET":
            calls["market"] += 1
            if calls["market"] < 3:
                raise RuntimeError("PERCENT_PRICE filter limit (code=-4131, http=400)")
            return {"orderId": 99, "avgPrice": "2.0", "executedQty": str(params.get("quantity") or 1)}
        raise RuntimeError(f"unexpected {method} {path} {params}")

    c._request_keepalive = fake_req  # type: ignore
    c._limit_ioc_close_leg = lambda **_k: {"ok": False, "error": "ioc_unfilled status=EXPIRED"}  # type: ignore
    c._limit_gtc_brief_close = lambda **_k: {"ok": False, "error": "gtc_unfilled"}  # type: ignore
    c.realized_pnl_for_order = lambda *_a, **_k: (0.0, 0.0)  # type: ignore
    c.invalidate_positions_cache = lambda: None  # type: ignore
    c._estimate_close_pnl = lambda *_a, **_k: 0.0  # type: ignore

    # Shrink budget for unit test speed via rounds / sleep constants already small for market path.
    r = c._persistent_escape_4131_close(
        symbol="ORCAUSDT",
        exit_side="BUY",
        quantity=10.0,
        hedge_side="SHORT",
        entry_price=2.0,
        budget_s=5.0,
    )
    assert r.get("ok"), r
    assert calls["market"] >= 3
    assert r.get("close_method") == "force_flat_4131"
    print("OK force_flat_4131 keeps retrying MARKET until fill")


def test_refuse_resume_while_stuck_close() -> None:
    from binance_connector import BinanceConnector, BinanceConfig
    from momentum_scanner import MomentumScanner

    c = BinanceConnector(BinanceConfig(paper=False, testnet=True, api_key="k", api_secret="s"))
    c._connected = True
    c.mark_signed_ready(reason="test")
    s = MomentumScanner(connector=c, get_testnet=lambda: True)
    s._user_exec_halted = True
    s._stuck_close_syms["ORCAUSDT"] = {"reason": "SHORT_TP", "ts": 1.0}
    s._connector.positions = lambda symbol=None, force=False, **_k: [  # type: ignore
        {"symbol": "ORCAUSDT", "positionSide": "SHORT", "volume": 1.0, "type": "SELL"}
    ]
    s.set_exec_enabled(True)
    assert s._user_exec_halted is True
    assert "ORCAUSDT" in s._stuck_close_syms
    print("OK refuse resume while stuck close residual remains")


if __name__ == "__main__":
    test_naked_short_exchange_target_is_5x()
    test_hedge_episode_blocks_solo_exit()
    test_pre_hedge_green_allows_solo()
    test_underwater_blocks_solo()
    test_no_hedge_at_or_past_invalidation()
    test_adopt_refreshes_without_overlap_flag()
    test_manage_never_forces_naked_10x()
    test_manual_open_qty_locked_to_partition()
    test_market_max_qty_clamped()
    test_short_entry_sync_never_deflates()
    test_close_chunks_market_max_and_longs_first()
    test_force_flat_4131_retries_until_fill()
    test_refuse_resume_while_stuck_close()
    from frozen_strategy import assert_frozen_contract

    assert_frozen_contract()
    print("OK frozen contract after violation locks")
    print("test_violation_locks: ALL OK")
