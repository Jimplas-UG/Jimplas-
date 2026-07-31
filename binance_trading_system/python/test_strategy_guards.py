#!/usr/bin/env python3
"""Hard policy floors — the primary-short trail and smart exit must be unbreakable,
while the original 50 / 40 / 40 short-first sizing passes through untouched."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from strategy_guards import (  # noqa: E402
    MIN_PULLBACK_PCT,
    MIN_SMART_EXIT_PCT_IF_ENABLED,
    SAFE_PRIMARY_SHORT_PCT,
    SAFE_RECOVERY_LEG_PCT,
    clamp_pullback_pct,
    clamp_smart_exit_pct,
    is_toxic_legacy_sizing,
    primary_notional_mult,
    recovery_notional_mult,
    sanitize_partitions,
)


def test_pullback_floor_blocks_half_pct_stop() -> None:
    assert clamp_pullback_pct(0.5) >= MIN_PULLBACK_PCT
    assert clamp_pullback_pct(0.1) == MIN_PULLBACK_PCT
    assert clamp_pullback_pct(2.0) == 2.0
    print("OK short-trail floor blocks 0.5% hard-stop regression")


def test_smart_exit_floor() -> None:
    assert clamp_smart_exit_pct(0) == 0.0
    assert clamp_smart_exit_pct(1.0) == MIN_SMART_EXIT_PCT_IF_ENABLED
    assert clamp_smart_exit_pct(8.0) == 8.0
    print("OK smart-exit floor blocks 1% noise exit")


def test_original_50_40_40_survives() -> None:
    assert not is_toxic_legacy_sizing(50, 40, 40)
    short_pct, l1, l2, changed = sanitize_partitions(50, 40, 40)
    assert not changed
    assert short_pct == 50.0
    assert l1 == 40.0 and l2 == 40.0
    print("OK original 50/40/40 short-first sizing is preserved")


def test_legacy_12_5_clamp_migrated_back() -> None:
    assert is_toxic_legacy_sizing(50, 12.5, 12.5)
    short_pct, l1, l2, changed = sanitize_partitions(50, 12.5, 12.5)
    assert changed
    assert short_pct == SAFE_PRIMARY_SHORT_PCT
    assert l1 == SAFE_RECOVERY_LEG_PCT and l2 == SAFE_RECOVERY_LEG_PCT
    print("OK long-first 12.5/12.5 clamp migrates back to 40/40")


def test_absurd_recovery_sizing_still_capped() -> None:
    assert is_toxic_legacy_sizing(10, 50, 50)
    short_pct, l1, l2, changed = sanitize_partitions(10, 50, 50)
    assert changed
    assert recovery_notional_mult(l1, l2) <= primary_notional_mult(short_pct) * 3.3 + 1e-9
    print("OK recovery notional stays inside the policy ratio")


def test_set_risk_keeps_policy_sizing(monkeypatch_path: str | None = None) -> None:
    os.environ.setdefault("SCANNER_EXEC", "1")
    os.environ.setdefault("SCANNER_LONG_DELAY_MS", "0")
    import momentum_scanner as ms
    from types import SimpleNamespace

    path = monkeypatch_path or os.path.join(tempfile.gettempdir(), "scanner-risk-guard-test.json")
    if os.path.isfile(path):
        os.remove(path)
    old = ms.RISK_CONFIG_PATH
    ms.RISK_CONFIG_PATH = path
    try:
        conn = SimpleNamespace(cfg=SimpleNamespace(paper=True, api_key=""), _connected=False)
        sc = ms.MomentumScanner(conn, lambda: True)
        r = sc.set_risk_config(partition_usd=100, short_pct=50, long1_pct=40, long2_pct=40)
        assert r.get("ok")
        assert sc._short_pct == 50.0
        assert sc._long1_pct == 40.0 and sc._long2_pct == 40.0
        assert not is_toxic_legacy_sizing(sc._short_pct, sc._long1_pct, sc._long2_pct)
        # A persisted long-first clamp must be migrated back on reload.
        with open(path, "w", encoding="utf-8") as fh:
            import json

            json.dump(
                {
                    "partition_usd": 100,
                    "short_pct": 50,
                    "long1_pct": 12.5,
                    "long2_pct": 12.5,
                    "locked": True,
                    "exec_halted": False,
                },
                fh,
            )
        sc2 = ms.MomentumScanner(conn, lambda: True)
        assert sc2._long1_pct == SAFE_RECOVERY_LEG_PCT and sc2._long2_pct == SAFE_RECOVERY_LEG_PCT
        assert sc2._risk_locked is False
    finally:
        ms.RISK_CONFIG_PATH = old
        if os.path.isfile(path):
            os.remove(path)
    print("OK set_risk / reload keep 50/40/40 and migrate the legacy clamp")


def test_short_trail_ignores_patched_half_pct() -> None:
    os.environ.setdefault("SCANNER_EXEC", "1")
    os.environ.setdefault("SCANNER_LONG_DELAY_MS", "0")
    import unittest.mock
    import momentum_scanner as ms
    from types import SimpleNamespace
    from momentum_scanner import LegPosition, MAGIC_SHORT, SHORT_LEVERAGE, STATUS_SHORT

    conn = SimpleNamespace(cfg=SimpleNamespace(paper=True, api_key=""), _connected=False)
    sc = ms.MomentumScanner(conn, lambda: True)
    # Attempt to regress the module constant — effective helper must still floor.
    old = ms.SHORT_TRAIL_PULLBACK_PCT
    ms.SHORT_TRAIL_PULLBACK_PCT = 0.5
    try:
        assert sc._effective_pullback_pct() >= MIN_PULLBACK_PCT
        # The recovery-long trail is intentionally NOT floored — it stays at 0.5%.
        assert sc._effective_long_pullback_pct() <= 0.5 + 1e-9
        sym = "HARDUSDT"
        sc.load_symbols([sym])
        sc.on_tick(sym, 100.0)
        coin = sc._coins[sym]
        coin.short = LegPosition("SELL", 100.0, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, None)
        coin.short_trough_price = 100.0
        coin.status = STATUS_SHORT
        coin.short_opened_ms = 1
        with unittest.mock.patch.object(ms, "SMART_EXIT_NET_PCT", 0.0):
            sc.on_tick(sym, 100.6)  # +0.6% against the short
        assert coin.short is not None, "must not hard-stop at +0.6% even if the constant is patched"
    finally:
        ms.SHORT_TRAIL_PULLBACK_PCT = old
    print("OK short-trail floor survives a patched 0.5% constant")


if __name__ == "__main__":
    try:
        test_pullback_floor_blocks_half_pct_stop()
        test_smart_exit_floor()
        test_original_50_40_40_survives()
        test_legacy_12_5_clamp_migrated_back()
        test_absurd_recovery_sizing_still_capped()
        test_set_risk_keeps_policy_sizing()
        test_short_trail_ignores_patched_half_pct()
    except AssertionError as e:
        print("FAIL", e, file=sys.stderr)
        raise SystemExit(1)
    print("test_strategy_guards: ALL OK")
