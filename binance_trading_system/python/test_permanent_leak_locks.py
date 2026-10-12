#!/usr/bin/env python3
"""Permanent leak locks — every Oct forensic class must stay closed forever."""
from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))

from binance_connector import BinanceConnector  # noqa: E402
from frozen_strategy import assert_frozen_contract  # noqa: E402
from leverage_policy import SHORT_LEVERAGE, symbol_exchange_leverage  # noqa: E402
from momentum_scanner import (  # noqa: E402
    ENTRY_COOLDOWN_MS,
    EPISODE_COOLDOWN_MS,
    INVALIDATION_COOLDOWN_MS,
    LONG_ENTRY_DELAY_MS,
    MAX_ADOPT_SHORT_NOTIONAL_MULT,
    MIN_QUOTE_VOL_24H,
    CoinStrategy,
    MomentumScanner,
)


ROOT = Path(__file__).resolve().parents[2]


def test_no_rule_kernel_safe_mode() -> None:
    assert not (Path(__file__).with_name("rule_kernel.py")).exists()
    src = Path(__file__).with_name("momentum_scanner.py").read_text(encoding="utf-8")
    assert "SAFE_MODE" not in src
    assert "rule_kernel" not in src.lower()
    print("OK no rule_kernel / SAFE_MODE")


def test_naked_short_never_10x() -> None:
    assert symbol_exchange_leverage(has_recovery_long=False) == SHORT_LEVERAGE == 5
    manage = inspect.getsource(MomentumScanner._manage_positions)
    assert "target = LONG1_LEVERAGE" not in manage
    print("OK naked short never forced 10x")


def test_hedged_short_tp_net_red_gate() -> None:
    conn = SimpleNamespace(cfg=SimpleNamespace(paper=True, api_key=""), _connected=False)
    sc = MomentumScanner(conn, lambda: True)
    coin = CoinStrategy(symbol="C98USDT")
    coin.short = SimpleNamespace(entry=100.0, qty=1.0, side="SELL")
    coin.long1 = SimpleNamespace(entry=102.0, qty=0.4, side="BUY")
    coin.unrealized_pnl = -40.0
    assert sc._hedged_short_exit_net_ok(coin) is False
    coin.unrealized_pnl = 5.0
    assert sc._hedged_short_exit_net_ok(coin) is True
    coin.long1 = None
    coin.unrealized_pnl = -1.0
    assert sc._hedged_short_exit_net_ok(coin) is True  # naked always OK
    print("OK hedged SHORT_TP net-red gate")


def test_solo_pullback_blocked_in_episode() -> None:
    conn = SimpleNamespace(cfg=SimpleNamespace(paper=True, api_key=""), _connected=False)
    sc = MomentumScanner(conn, lambda: True)
    coin = CoinStrategy(symbol="TESTUSDT")
    coin.short = SimpleNamespace(entry=100.0, qty=1.0, side="SELL", leverage=5, magic=88001, tp_price=0)
    coin.price = 99.0
    coin.short_adverse_peak_pct = 2.5
    coin.long1 = SimpleNamespace(entry=102.0, qty=0.4, side="BUY")
    assert sc._solo_hedge_exit_allowed(coin) is False
    print("OK solo LONG pullback blocked in hedge episode")


def test_manual_oversize_clamp_aave_class() -> None:
    conn = SimpleNamespace(cfg=SimpleNamespace(paper=True, api_key=""), _connected=False)
    sc = MomentumScanner(conn, lambda: True)
    # AAVE-class: 19.3 @ 180 ≈ $3474 vs ~$250 short cap
    qty, rejected = sc.clamp_manual_open_qty("AAVEUSDT", "SELL", 180.0, 19.3)
    assert rejected is True
    assert qty <= sc.max_manual_open_qty("AAVEUSDT", "SELL", 180.0) + 1e-9
    print("OK AAVE-class manual oversize clamped")


def test_adopt_oversize_short_refused() -> None:
    conn = SimpleNamespace(cfg=SimpleNamespace(paper=True, api_key=""), _connected=False)
    sc = MomentumScanner(conn, lambda: True)
    assert sc._locked_short_notional_usd() == 250.0
    assert sc._short_notional_within_partition(1.0, 250.0) is True
    assert sc._short_notional_within_partition(19.3, 180.0) is False
    assert MAX_ADOPT_SHORT_NOTIONAL_MULT == 1.25
    print("OK adopt oversize short refused")


def test_cool_never_instant_flatten() -> None:
    cool = inspect.getsource(BinanceConnector._wait_or_clear_cool_for_close)
    assert "max_wait_s: float = 12.0" in cool
    assert "forced to 12s" in cool or "ignoring max_wait_s" in cool
    assert "immediate flatten" not in cool
    assert "if max_wait_s <= 0" in cool
    print("OK cool never instant-flatten (max_wait_s=0 forced to 12s)")


def test_portal_short_refuses_long_residual() -> None:
    side = inspect.getsource(BinanceConnector.close_by_position_side)
    assert "long_residual_abort_short" in side
    close = inspect.getsource(BinanceConnector.close_position)
    assert "long_residual_abort_short" in close
    print("OK PORTAL SHORT refuses LONG residual")


def test_desk_quality_floors() -> None:
    assert MIN_QUOTE_VOL_24H >= 10_000_000
    assert INVALIDATION_COOLDOWN_MS >= 1_200_000
    assert EPISODE_COOLDOWN_MS >= 600_000
    assert ENTRY_COOLDOWN_MS >= 300_000
    assert LONG_ENTRY_DELAY_MS >= 3_000
    print("OK liquidity + episode cool + settle floors")


def test_api_close_never_invents_flat_on_429() -> None:
    main_src = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    assert "_force_positions_or_503" in main_src
    assert "PositionsUnavailable" in main_src
    print("OK api_close 429 -> 503 not flat")


def test_client_close_429_waits_cool_window() -> None:
    fe = ROOT / "frontend" / "broker" / "binanceFuturesApi.js"
    assert fe.exists(), f"missing {fe}"
    src = fe.read_text(encoding="utf-8")
    assert "waitS * 1000" in src
    assert "Math.min(Math.max(Number(m?.[1]) || 3, 1), 12)" in src
    assert "positions_unavailable" in src
    # Must not use the old 400ms stub as the 429 path.
    assert "res.status === 429 && attempt < 2" not in src or "waitS" in src.split("429")[1][:400]
    print("OK client close 429 waits <=12s cool window")


def test_ui_manual_close_requires_confirm() -> None:
    panel = ROOT / "frontend" / "components" / "OpenPositionsPanel.js"
    assert panel.exists(), f"missing {panel}"
    src = panel.read_text(encoding="utf-8")
    assert "confirmCloseLeg" in src
    assert "Cancel" in src
    assert "Alert.alert" in src
    print("OK UI manual close requires confirm dialog")


def test_ghost_floating_same_symbol_only() -> None:
    pnl = ROOT / "frontend" / "lib" / "liveFloatingPnl.js"
    assert pnl.exists(), f"missing {pnl}"
    src = pnl.read_text(encoding="utf-8")
    assert "MAX_MARK_REL_MOVE" in src
    assert "heroFloatingPnl" in src
    assert "resolveLegMark" in src
    test = ROOT / "frontend" / "lib" / "liveFloatingPnl.test.js"
    assert test.exists()
    print("OK ghost floating same-symbol mark lock present")


def test_frozen_contract_includes_permanent_locks() -> None:
    snap = assert_frozen_contract()
    assert snap["strategy_id"] == "short_first_v1"
    assert abs(float(snap["ops"]["partition_usd"]) - 100.0) < 1e-9
    print("OK frozen contract includes permanent leak locks")


def test_exchange_positions_never_empty_on_unavailable() -> None:
    from binance_connector import PositionsUnavailable

    class Conn:
        cfg = SimpleNamespace(paper=False, api_key="k")

        def confirmed_positions(self, *a, **k):
            raise PositionsUnavailable("REST cooling (429) 5s — positions unconfirmed")

        def positions(self, *a, **k):
            raise PositionsUnavailable("REST cooling (429) 5s — positions unconfirmed")

    sc = MomentumScanner(Conn(), lambda: True)  # type: ignore[arg-type]
    raised = False
    try:
        sc._exchange_positions()
    except PositionsUnavailable:
        raised = True
    assert raised, "unavailable must raise — never return []"
    # Gate path fails closed using scanner state, not empty book.
    coin = CoinStrategy(symbol="USUSDT")
    coin.short = SimpleNamespace(qty=1.0, entry=1.0, side="SELL")
    sc._coins["USUSDT"] = coin
    rows = sc._exchange_positions_for_gate()
    assert any(str(r.get("symbol")) == "USUSDT" for r in rows)
    print("OK exchange_positions raises; gate uses scanner opens")


def test_short_gone_defers_when_confirm_unavailable() -> None:
    from binance_connector import PositionsUnavailable
    from momentum_scanner import LegPosition, STATUS_SHORT

    class Conn:
        cfg = SimpleNamespace(paper=False, api_key="k")
        _rest_cool_reason = "429"

        def rest_cooling_left(self):
            return 5.0

        def exchange_short_qty(self, symbol, max_age_s=1.5):
            return 0.0  # first sample looks flat

        def exchange_long_qty(self, symbol, max_age_s=1.5):
            return 0.0

        def confirmed_positions(self, *a, **k):
            raise PositionsUnavailable("REST cooling (429) — positions unconfirmed")

    sc = MomentumScanner(Conn(), lambda: True)  # type: ignore[arg-type]
    coin = CoinStrategy(symbol="RLCUSDT")
    coin.short = LegPosition("SELL", 1.0, 10.0, 5, 88001, 0.97)
    coin.status = STATUS_SHORT
    sc._coins["RLCUSDT"] = coin
    kept = sc._ensure_pair_coherence(coin)
    assert kept is True
    assert coin.short is not None, "must not SHORT_GONE on unavailable confirm"
    print("OK SHORT_GONE defers when confirm unavailable")


def test_confirmed_positions_trusts_last_good_during_cool() -> None:
    from binance_connector import BinanceConnector, BinanceConfig, PositionsUnavailable
    import time as _t

    c = BinanceConnector(BinanceConfig(paper=False, testnet=True, api_key="k", api_secret="s"))
    c._last_good_positions = [
        {"symbol": "BTCUSDT", "volume": 1.0, "positionSide": "SHORT", "type": "SELL"}
    ]
    c._last_good_positions_ts = _t.time() - 5.0  # older than 1.5s default
    c._rest_cool_until = _t.monotonic() + 20.0
    c._rest_cool_reason = "429"
    rows = c.confirmed_positions("BTCUSDT", max_age_s=1.5)
    assert len(rows) == 1 and rows[0]["symbol"] == "BTCUSDT"
    # No last_good and cool → unavailable (not force spam)
    c._last_good_positions_ts = 0.0
    raised = False
    try:
        c.confirmed_positions("BTCUSDT", max_age_s=1.5)
    except PositionsUnavailable:
        raised = True
    assert raised
    print("OK confirmed_positions trusts last_good up to 30s during cool")


def test_close_by_side_never_ok_with_residual() -> None:
    """PORTAL class: close_by_position_side must not return ok while side still live."""
    from binance_connector import BinanceConnector, BinanceConfig

    c = BinanceConnector(BinanceConfig(paper=False, testnet=True, api_key="k", api_secret="s"))
    c._hedge_mode = True
    calls = {"n": 0}

    def fake_positions(symbol=None, force=False, bypass_rest_cool=False):
        calls["n"] += 1
        # Always report leftover LONG — residual gate must fail closed.
        return [{"symbol": "PORTALUSDT", "volume": 50000.0, "positionSide": "LONG", "type": "BUY", "price_open": 1.0}]

    def fake_request(*_a, **_k):
        raise RuntimeError("should not MARKET when we stub loop — use residual path")

    c.positions = fake_positions  # type: ignore
    c.get_symbol_spec = lambda _s: {  # type: ignore
        "marketStepSize": 1.0,
        "stepSize": 1.0,
        "marketMinQty": 1.0,
        "minQty": 1.0,
        "marketMaxQty": 30000.0,
        "maxQty": 30000.0,
    }
    c.cancel_all_orders = lambda *_a, **_k: None  # type: ignore
    c._wait_or_clear_cool_for_close = lambda **_k: 0.0  # type: ignore
    c._request_keepalive = fake_request  # type: ignore
    c._market_close_params = lambda **k: k  # type: ignore
    c.apply_symbol_positions_snapshot = lambda *_a, **_k: None  # type: ignore
    c.remember_close_deals = lambda *_a, **_k: None  # type: ignore

    # Force path: empty closed chunks then residual check — volume=None full close.
    # Simulate loop exit with remaining=0 local but live residual via _position_side_qty.
    c._position_side_qty = lambda _s, _ps: 50000.0  # type: ignore
    # Hijack the while-loop by making first positions empty for targets... need targets.
    # Re-stub: first call returns target, subsequent residual via _position_side_qty.
    state = {"i": 0}

    def pos2(symbol=None, force=False, bypass_rest_cool=False):
        state["i"] += 1
        return [
            {
                "symbol": "PORTALUSDT",
                "volume": 100.0,
                "positionSide": "LONG",
                "type": "BUY",
                "price_open": 1.0,
            }
        ]

    c.positions = pos2  # type: ignore

    # MARKET succeeds with missing executedQty → must not invent full chunk.
    def keepalive(*_a, **_k):
        return {"orderId": 1, "avgPrice": "1.0"}  # no executedQty

    c._request_keepalive = keepalive  # type: ignore
    c.query_order_by_client_id = lambda *_a, **_k: None  # type: ignore
    c.realized_pnl_for_order = lambda *_a, **_k: (0.0, 0.0)  # type: ignore
    c._sanitize_fill_price = lambda *_a, **_k: 1.0  # type: ignore
    c._estimate_close_pnl = lambda *_a, **_k: 0.0  # type: ignore
    c._finalize_close_pnl = lambda *_a, **_k: 0.0  # type: ignore

    r = c.close_by_position_side("PORTALUSDT", "LONG", None)
    assert r.get("ok") is False, r
    assert "zero_executed" in str(r.get("error") or "") or "partial_close" in str(r.get("error") or ""), r
    print("OK close_by_position_side never invents fill / ok-with-residual")


def test_mandatory_exits_force_through_backoff() -> None:
    from momentum_scanner import MomentumScanner, CoinStrategy
    import inspect

    src = inspect.getsource(MomentumScanner._manage_positions)
    assert 'self._close_all(coin, "INVALIDATION", force=True)' in src
    assert 'self._close_all(coin, "RESCUE", force=True)' in src
    assert 'self._close_all(coin, "SMART_EXIT", force=True)' in src
    assert "arm_hedges" in src
    print("OK INVALIDATION/RESCUE/SMART_EXIT force through close_backoff")


def test_global_active_fail_closed_on_unavailable() -> None:
    from binance_connector import PositionsUnavailable
    from momentum_scanner import MomentumScanner

    sc = MomentumScanner(SimpleNamespace(cfg=SimpleNamespace(paper=False, api_key="k")), lambda: True)
    sc._last_known_active_symbol = "WUSDT"

    def boom():
        raise PositionsUnavailable("cool")

    sc._exchange_positions = boom  # type: ignore
    assert sc._global_active_symbol() == "WUSDT"
    print("OK global_active fail-closed keeps last known symbol")


def test_manual_clamp_residual_aware() -> None:
    from momentum_scanner import MomentumScanner

    conn = SimpleNamespace(
        cfg=SimpleNamespace(paper=False, api_key="k"),
        exchange_short_qty=lambda _s: 10.0,
        exchange_long_qty=lambda _s: 0.0,
        symbol_spec=lambda *_a, **_k: {"stepSize": 0.001, "minQty": 0.001},
    )
    sc = MomentumScanner(conn, lambda: True)
    sc._partition_usd = 100.0
    # max short qty at price 1 ≈ 50*5=250 notional → qty 250; live 10 → room 240
    qty, rejected = sc.clamp_manual_open_qty("BTCUSDT", "SELL", 1.0, 1000.0)
    assert rejected is True
    assert qty < 1000.0
    # Already at/over cap
    conn.exchange_short_qty = lambda _s: 10_000.0
    qty2, rej2 = sc.clamp_manual_open_qty("BTCUSDT", "SELL", 1.0, 1.0)
    assert rej2 is True and qty2 == 0.0
    print("OK manual clamp residual-aware (no stack past partition)")


def test_exit_outcome_recorded_on_incomplete() -> None:
    from momentum_scanner import MomentumScanner, CoinStrategy, STATUS_SHORT

    conn = SimpleNamespace(cfg=SimpleNamespace(paper=True, api_key=""), _connected=False)
    sc = MomentumScanner(conn, lambda: True)
    coin = CoinStrategy(symbol="XUSDT")
    coin.short = SimpleNamespace(entry=1.0, qty=1.0, side="SELL", leverage=5, magic=88001, tp_price=0)
    coin.status = STATUS_SHORT

    def fail_close(_sym, _magic, _qty):
        return {"ok": False, "error": "simulated"}

    conn.close_leg = fail_close
    r = sc._close_all(coin, "INVALIDATION", force=True)
    assert r.get("ok") is False
    outs = sc.recent_exit_outcomes()
    assert outs and outs[-1]["ok"] is False and outs[-1]["reason"] == "INVALIDATION"
    assert coin.short is not None, "must not clear scanner state on failed exit"
    print("OK failed exit records outcome and preserves state")


if __name__ == "__main__":
    test_no_rule_kernel_safe_mode()
    test_naked_short_never_10x()
    test_hedged_short_tp_net_red_gate()
    test_solo_pullback_blocked_in_episode()
    test_manual_oversize_clamp_aave_class()
    test_adopt_oversize_short_refused()
    test_cool_never_instant_flatten()
    test_portal_short_refuses_long_residual()
    test_desk_quality_floors()
    test_api_close_never_invents_flat_on_429()
    test_client_close_429_waits_cool_window()
    test_ui_manual_close_requires_confirm()
    test_ghost_floating_same_symbol_only()
    test_frozen_contract_includes_permanent_locks()
    test_exchange_positions_never_empty_on_unavailable()
    test_short_gone_defers_when_confirm_unavailable()
    test_confirmed_positions_trusts_last_good_during_cool()
    test_close_by_side_never_ok_with_residual()
    test_mandatory_exits_force_through_backoff()
    test_global_active_fail_closed_on_unavailable()
    test_manual_clamp_residual_aware()
    test_exit_outcome_recorded_on_incomplete()
    print("test_permanent_leak_locks: ALL OK")
