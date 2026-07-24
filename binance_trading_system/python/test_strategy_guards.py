#!/usr/bin/env python3
"""Hard policy floors — toxic knobs must be unbreakable."""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from strategy_guards import (  # noqa: E402
    MIN_PULLBACK_PCT,
    MIN_SMART_EXIT_PCT_IF_ENABLED,
    SAFE_RECOVERY_LEG_PCT,
    clamp_pullback_pct,
    clamp_smart_exit_pct,
    is_toxic_legacy_sizing,
    sanitize_partitions,
    short_notional_mult,
    long_notional_mult,
)


def test_pullback_floor_blocks_half_pct_stop() -> None:
    assert clamp_pullback_pct(0.5) >= MIN_PULLBACK_PCT
    assert clamp_pullback_pct(0.1) == MIN_PULLBACK_PCT
    assert clamp_pullback_pct(2.0) == 2.0
    print("OK pullback floor blocks 0.5% hard-stop regression")


def test_smart_exit_floor() -> None:
    assert clamp_smart_exit_pct(0) == 0.0
    assert clamp_smart_exit_pct(1.0) == MIN_SMART_EXIT_PCT_IF_ENABLED
    assert clamp_smart_exit_pct(8.0) == 8.0
    print("OK smart-exit floor blocks 1% noise exit")


def test_toxic_40_40_sanitized() -> None:
    assert is_toxic_legacy_sizing(50, 40, 40)
    long_pct, s1, s2, changed = sanitize_partitions(50, 40, 40)
    assert changed
    assert s1 == SAFE_RECOVERY_LEG_PCT and s2 == SAFE_RECOVERY_LEG_PCT
    assert short_notional_mult(s1, s2) <= long_notional_mult(long_pct) * 1.25 + 1e-9
    print("OK toxic 40/40 sanitized to balanced shorts")


def test_set_risk_cannot_lock_toxic(monkeypatch_path: str | None = None) -> None:
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
        assert sc._long1_pct <= 15.0 and sc._long2_pct <= 15.0
        assert not is_toxic_legacy_sizing(sc._short_pct, sc._long1_pct, sc._long2_pct)
        # Reload must keep sanitized values even if file was hand-edited toxic.
        with open(path, "w", encoding="utf-8") as fh:
            import json

            json.dump(
                {
                    "partition_usd": 100,
                    "short_pct": 50,
                    "long1_pct": 40,
                    "long2_pct": 40,
                    "locked": True,
                    "exec_halted": False,
                },
                fh,
            )
        sc2 = ms.MomentumScanner(conn, lambda: True)
        assert sc2._long1_pct <= 15.0 and sc2._long2_pct <= 15.0
        assert sc2._risk_locked is False
    finally:
        ms.RISK_CONFIG_PATH = old
        if os.path.isfile(path):
            os.remove(path)
    print("OK set_risk / reload cannot lock toxic 40/40")


def test_runtime_pullback_ignores_patched_half_pct() -> None:
    os.environ.setdefault("SCANNER_EXEC", "1")
    os.environ.setdefault("SCANNER_LONG_DELAY_MS", "0")
    import unittest.mock
    import momentum_scanner as ms
    from types import SimpleNamespace
    from momentum_scanner import LegPosition, MAGIC_LONG1, SHORT_LEVERAGE, STATUS_LONG1

    conn = SimpleNamespace(cfg=SimpleNamespace(paper=True, api_key=""), _connected=False)
    sc = ms.MomentumScanner(conn, lambda: True)
    # Attempt to regress module constant — effective helpers must still floor.
    old = ms.LONG_BOTH_PULLBACK_PCT
    ms.LONG_BOTH_PULLBACK_PCT = 0.5
    try:
        assert sc._effective_pullback_pct() >= MIN_PULLBACK_PCT
        sym = "HARDUSDT"
        sc.load_symbols([sym])
        sc.on_tick(sym, 100.0)
        coin = sc._coins[sym]
        coin.long1 = LegPosition("BUY", 100.0, 1.0, SHORT_LEVERAGE, MAGIC_LONG1, None)
        coin.long1_peak_price = 100.0
        coin.status = STATUS_LONG1
        coin.long1_opened_ms = 1
        with unittest.mock.patch.object(ms, "SMART_EXIT_NET_PCT", 0.0):
            sc.on_tick(sym, 99.4)  # -0.6%
        assert coin.long1 is not None, "must not hard-stop at -0.6% even if constant patched to 0.5"
    finally:
        ms.LONG_BOTH_PULLBACK_PCT = old
    print("OK runtime pullback floor survives patched 0.5% constant")


if __name__ == "__main__":
    try:
        test_pullback_floor_blocks_half_pct_stop()
        test_smart_exit_floor()
        test_toxic_40_40_sanitized()
        test_set_risk_cannot_lock_toxic()
        test_runtime_pullback_ignores_patched_half_pct()
    except AssertionError as e:
        print("FAIL", e, file=sys.stderr)
        raise SystemExit(1)
    print("test_strategy_guards: ALL OK")
