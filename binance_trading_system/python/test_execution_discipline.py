#!/usr/bin/env python3
"""Execution discipline regressions — Sep23-25 clean paths + adversarial failure locks.

Evidence format: TEST / EXPECTED / ACTUAL / STATUS
No strategy redesign — only risk/execution locks.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))

from rule_kernel import (
    LiveState,
    audit_live_state,
    preflight_solo_hedge_exit,
    should_emergency_halt,
)


def _row(test: str, expected: str, actual: str, ok: bool) -> None:
    status = "PASS" if ok else "FAIL"
    print(f"TEST={test}")
    print(f"EXPECTED={expected}")
    print(f"ACTUAL={actual}")
    print(f"STATUS={status}")
    assert ok, f"{test}: expected {expected!r} got {actual!r}"


def test_oversize_external_short_halts() -> None:
    # Locked short notional = 100 * 0.5 * 5 = 250. AAVE-class ~3479 must halt.
    state = LiveState(
        symbol="AAVEUSDT",
        has_exchange_short=True,
        has_scanner_short=True,
        scanner_short_qty=19.3,
        exchange_short_qty=19.3,
        short_entry=180.26,
        short_notional_usd=19.3 * 180.26,
        max_short_notional_usd=250.0,
    )
    codes = audit_live_state(state)
    ok = "OVERSIZE_EXTERNAL_SHORT" in codes and should_emergency_halt(codes)
    _row(
        "OVERSIZE_EXTERNAL_SHORT_HALT",
        "OVERSIZE_EXTERNAL_SHORT in halt codes",
        str(codes),
        ok,
    )


def test_partition_sized_short_clean() -> None:
    state = LiveState(
        symbol="CETUSUSDT",
        has_exchange_short=True,
        has_scanner_short=True,
        scanner_short_qty=2500.0,
        exchange_short_qty=2500.0,
        short_entry=0.1,
        short_notional_usd=250.0,
        max_short_notional_usd=250.0,
    )
    codes = audit_live_state(state)
    ok = "OVERSIZE_EXTERNAL_SHORT" not in codes
    _row(
        "PARTITION_SHORT_CLEAN",
        "no OVERSIZE_EXTERNAL_SHORT",
        str(codes),
        ok,
    )


def test_solo_hedge_blocked_after_episode() -> None:
    v = preflight_solo_hedge_exit(
        short_open=True,
        hedge_episode_active=True,
        short_underwater=False,
    )
    ok = (not v.ok) and v.code == "SOLO_EXIT_BLOCK"
    _row(
        "SOLO_HEDGE_EXIT_BLOCK",
        "blocked SOLO_EXIT_BLOCK",
        f"ok={v.ok} code={v.code}",
        ok,
    )


def test_close_success_requires_exchange_flat() -> None:
    from momentum_scanner import MomentumScanner
    from binance_connector import BinanceConnector, BinanceConfig

    c = BinanceConnector(BinanceConfig(paper=False, testnet=True, api_key="k", api_secret="s"))
    s = MomentumScanner(connector=c, get_testnet=lambda: True)
    # Fake residual on exchange
    c.positions = lambda symbol=None, force=False, **_k: [  # type: ignore
        {"symbol": "ORCAUSDT", "volume": 1.0, "positionSide": "SHORT", "type": "SELL"}
    ]
    ok_fail = not s._close_succeeded({"ok": True, "closed": [{"order": 1}]}, "ORCAUSDT")
    c.positions = lambda symbol=None, force=False, **_k: []  # type: ignore
    ok_pass = s._close_succeeded({"ok": True, "closed": [{"order": 1}]}, "ORCAUSDT")
    _row(
        "CLOSE_VERIFY_BEFORE_CLOSED",
        "residual=False flat=True",
        f"residual_ok={ok_fail} flat_ok={ok_pass}",
        ok_fail and ok_pass,
    )


def test_stuck_close_blocks_session() -> None:
    from momentum_scanner import MomentumScanner
    from binance_connector import BinanceConnector, BinanceConfig

    c = BinanceConnector(BinanceConfig(paper=False, testnet=True, api_key="k", api_secret="s"))
    c._connected = True
    c.mark_signed_ready(reason="test")
    s = MomentumScanner(connector=c, get_testnet=lambda: True)
    s._user_exec_halted = False
    s._stuck_close_syms["ORCAUSDT"] = {"reason": "SHORT_TP", "ts": 1.0}
    can, block = s._order_session_ok()
    ok = (not can) and "SAFE_MODE_STUCK_CLOSE" in block
    _row(
        "STUCK_CLOSE_BLOCKS_ENTRIES",
        "can_execute=False SAFE_MODE_STUCK_CLOSE",
        f"can={can} block={block}",
        ok,
    )


def test_oversize_blocks_l1() -> None:
    from momentum_scanner import MomentumScanner, CoinStrategy, LegPosition, MAGIC_SHORT, SHORT_LEVERAGE
    from binance_connector import BinanceConnector, BinanceConfig

    c = BinanceConnector(BinanceConfig(paper=False, testnet=True, api_key="k", api_secret="s"))
    s = MomentumScanner(connector=c, get_testnet=lambda: True)
    coin = CoinStrategy(symbol="AAVEUSDT")
    coin.short = LegPosition("SELL", 180.26, 19.3, SHORT_LEVERAGE, MAGIC_SHORT, 170.0)
    coin.price = 181.0
    # Avoid exchange REST — stub short present
    s._exchange_has_short = lambda _sym: True  # type: ignore
    s._exchange_long_covers_recovery = lambda *_a, **_k: False  # type: ignore
    s._short_settle_elapsed = lambda _c: True  # type: ignore
    allowed = s._long1_entry_allowed(coin)
    ok = allowed is False and "AAVEUSDT" in s._oversize_external_syms
    _row(
        "OVERSIZE_BLOCKS_L1_ADD",
        "long1_entry_allowed=False + oversize flagged",
        f"allowed={allowed} oversize={sorted(s._oversize_external_syms)}",
        ok,
    )


def test_force_flat_4131_and_chunk_markers() -> None:
    import inspect
    from binance_connector import BinanceConnector

    close_src = inspect.getsource(BinanceConnector.close_position)
    esc_src = inspect.getsource(BinanceConnector._persistent_escape_4131_close)
    ok = (
        "apply_symbol_positions_snapshot" in close_src
        and "long_residual_abort_short" in close_src
        and "force_flat_4131" in esc_src
        and "marketMaxQty" in close_src
    )
    _row(
        "CLOSE_PATH_4005_4131_MARKERS",
        "chunk+abort LONG residual+force_flat+sticky sync",
        f"markers_ok={ok}",
        ok,
    )


def _close_cache_status(ok: bool, result: dict) -> str:
    """Mirror main._close_op_finish status rules (no FastAPI import required)."""
    st = str(result.get("status") or "")
    if st == "CLOSE_PENDING_VERIFY" or result.get("close_pending") or (
        ok and result.get("verified_flat") is False
    ):
        return "CLOSE_PENDING_VERIFY"
    if st == "CLOSING" or result.get("verify_error"):
        return "CLOSING"
    if ok:
        return "CLOSED"
    return "CLOSE_FAILED"


def test_pending_verify_not_cached_as_closed() -> None:
    main_path = Path(__file__).resolve().parent / "main.py"
    src = main_path.read_text(encoding="utf-8")
    markers = (
        'cache_status = "CLOSE_PENDING_VERIFY"' in src
        and 'st in ("CLOSE_FAILED", "CLOSE_PENDING_VERIFY")' in src
        and "Never label CLOSE_PENDING_VERIFY as CLOSED" in src
        and 'result.get("verified_flat") is False' in src
        and 'result.get("close_pending")' in src
    )
    # Pure status decision must not promote pending verify to CLOSED
    pending = _close_cache_status(
        True,
        {
            "ok": True,
            "status": "CLOSE_PENDING_VERIFY",
            "verified_flat": False,
            "close_pending": True,
            "remaining": [{"volume": 1}],
        },
    )
    flat_ok = _close_cache_status(True, {"ok": True, "verified_flat": True, "status": "CLOSED"})
    unverified_ok = _close_cache_status(True, {"ok": True, "verified_flat": False})
    ok = (
        markers
        and pending == "CLOSE_PENDING_VERIFY"
        and flat_ok == "CLOSED"
        and unverified_ok == "CLOSE_PENDING_VERIFY"
    )
    _row(
        "IDEMPOTENT_PENDING_NOT_CLOSED",
        "cache=CLOSE_PENDING_VERIFY; verified_flat False never CLOSED",
        f"pending={pending} flat={flat_ok} unverified={unverified_ok} markers={markers}",
        ok,
    )


if __name__ == "__main__":
    test_oversize_external_short_halts()
    test_partition_sized_short_clean()
    test_solo_hedge_blocked_after_episode()
    test_close_success_requires_exchange_flat()
    test_stuck_close_blocks_session()
    test_oversize_blocks_l1()
    test_force_flat_4131_and_chunk_markers()
    test_pending_verify_not_cached_as_closed()
    print("test_execution_discipline: ALL OK")
