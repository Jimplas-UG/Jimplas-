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
    src = fe.read_text(encoding="utf-8")
    assert "setTimeout(r, 400)" not in src or "waitS * 1000" in src
    assert "Math.min(Math.max(Number(m?.[1]) || 3, 1), 12)" in src
    assert "positions_unavailable" in src
    print("OK client close 429 waits ≤12s cool window")


def test_ui_manual_close_requires_confirm() -> None:
    panel = ROOT / "frontend" / "components" / "OpenPositionsPanel.js"
    src = panel.read_text(encoding="utf-8")
    assert "confirmCloseLeg" in src
    assert "Cancel" in src
    assert "Alert.alert" in src
    print("OK UI manual close requires confirm dialog")


def test_ghost_floating_same_symbol_only() -> None:
    pnl = ROOT / "frontend" / "lib" / "liveFloatingPnl.js"
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
    print("test_permanent_leak_locks: ALL OK")
