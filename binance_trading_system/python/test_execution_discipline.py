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


def test_resolve_fill_via_query_not_invent() -> None:
    from binance_connector import BinanceConnector, BinanceConfig

    c = BinanceConnector(BinanceConfig(paper=True))
    # ACK has no qty — inventing chunk size is forbidden; query returns fill.
    c.query_order = lambda symbol, order_id: {  # type: ignore
        "orderId": order_id,
        "executedQty": "12.5",
        "avgPrice": "1.5",
        "status": "FILLED",
    }
    qty, px, src = c._resolve_executed_qty(
        {"orderId": 99, "executedQty": "0", "avgPrice": "0"},
        symbol="MOVRUSDT",
        order_id=99,
    )
    ok = qty == 12.5 and abs(px - 1.5) < 1e-9 and src == "query"
    _row(
        "RESOLVE_FILL_VIA_QUERY",
        "ACK empty -> GET order fill; never invent",
        f"qty={qty} px={px} src={src}",
        ok,
    )


def test_resolve_fill_unverified_no_invent() -> None:
    from binance_connector import BinanceConnector, BinanceConfig

    c = BinanceConnector(BinanceConfig(paper=True))
    c.query_order = lambda symbol, order_id: None  # type: ignore
    qty, px, src = c._resolve_executed_qty(
        {"orderId": 1},
        symbol="PORTALUSDT",
        order_id=1,
        pre_pos_qty=None,
    )
    ok = qty == 0.0 and src == "unverified"
    _row(
        "RESOLVE_FILL_UNVERIFIED",
        "no ACK/query/delta -> qty=0 unverified",
        f"qty={qty} src={src}",
        ok,
    )


def test_close_succeeded_exchange_flat_wins() -> None:
    from momentum_scanner import MomentumScanner

    sc = MomentumScanner.__new__(MomentumScanner)
    sc._connector = SimpleNamespace(
        cfg=SimpleNamespace(paper=False),
        positions=lambda symbol, force=True: [],
    )
    # Soft failure ACK but exchange already flat → success
    ok = sc._close_succeeded({"ok": False, "error": "ack_missing_executedQty"}, "MOVRUSDT")
    # Residual still open → fail even if ok=True
    sc._connector.positions = lambda symbol, force=True: [{"volume": 10, "positionSide": "SHORT"}]
    bad = sc._close_succeeded({"ok": True, "closed": [{}]}, "MOVRUSDT")
    _row(
        "CLOSE_SUCCESS_EXCHANGE_WINS",
        "flat+soft_fail=True; residual+ok=False",
        f"flat_soft={ok} residual_ok={bad}",
        ok is True and bad is False,
    )


def test_incomplete_close_always_safe_mode() -> None:
    from momentum_scanner import MomentumScanner
    from pair_isolation import pair_gate as pg

    sc = MomentumScanner.__new__(MomentumScanner)
    sc._coins = {}
    sc._user_exec_halted = False
    sc._rule_halt_codes = []
    sc._rule_halt_ts = 0.0
    sc._stuck_close_syms = {}
    sc._stuck_close_retry_ms = {}
    sc._close_backoff = {}
    sc._last_exec_error = None
    sc._one_at_a_time = False
    sc._on_snapshot = None
    calls: list[str] = []

    def _enter(reason: str, *, codes=None):
        calls.append(reason)
        sc._user_exec_halted = True
        sc._rule_halt_codes = list(codes or [])

    sc._enter_safe_mode = _enter  # type: ignore
    sc._mark_stuck_close = lambda sym, reason, remaining=None: sc._stuck_close_syms.__setitem__(  # type: ignore
        sym.upper(), {"reason": reason, "remaining": remaining}
    )
    sc._note_close_failure = lambda *a, **k: None  # type: ignore
    sc._close_backoff_active = lambda sym: False  # type: ignore
    sc._close_succeeded = lambda r, symbol=None: False  # type: ignore
    sc._connector = SimpleNamespace(
        cfg=SimpleNamespace(paper=False),
        positions=lambda symbol, force=True, bypass_rest_cool=False: [
            {"positionSide": "SHORT", "volume": 5.0, "type": "SELL"}
        ],
        close_position=lambda symbol, side: {"ok": False, "error": "ack_missing_executedQty", "closed": []},
    )
    coin = SimpleNamespace(symbol="MOVRUSDT", short=object(), long1=None, long2=None)
    real_begin, real_end, real_rec = pg.begin_close, pg.end_close, pg.record_order
    pg.begin_close = lambda *a, **k: None  # type: ignore
    pg.end_close = lambda *a, **k: None  # type: ignore
    pg.record_order = lambda **k: None  # type: ignore
    try:
        r = MomentumScanner._close_all(sc, coin, "RESCUE", force=True)
    finally:
        pg.begin_close, pg.end_close, pg.record_order = real_begin, real_end, real_rec
    ok = (
        r.get("ok") is False
        and "CLOSE_INCOMPLETE" in calls
        and "MOVRUSDT" in sc._stuck_close_syms
        and bool(r.get("remaining"))
    )
    _row(
        "INCOMPLETE_CLOSE_SAFE_MODE",
        "ack_missing without remaining[] still SAFE_MODE+stuck",
        f"ok={r.get('ok')} calls={calls} stuck={list(sc._stuck_close_syms)} rem={r.get('remaining')}",
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


def test_reset_leverage_if_flat_marker() -> None:
    from binance_connector import BinanceConnector
    import inspect

    ok = hasattr(BinanceConnector, "reset_leverage_if_flat") and hasattr(
        BinanceConnector, "_limit_ioc_open_leg"
    )
    src = inspect.getsource(BinanceConnector.place_market_order)
    ok = ok and "_limit_ioc_open_leg" in src
    _row(
        "POST_FLAT_LEV_AND_HEDGE_OPEN_4131",
        "reset_leverage_if_flat + limit_ioc_open on LONG -4131",
        f"ok={ok}",
        ok,
    )


def test_ensure_leverage_ignores_sticky_ghost() -> None:
    """Flat book with sticky ghost must still allow 5x reset (no false reduce_blocked)."""
    from binance_connector import BinanceConnector, BinanceConfig

    c = BinanceConnector(BinanceConfig(paper=False, testnet=True, api_key="k", api_secret="s"))
    c._last_good_positions = [{"symbol": "EDUUSDT", "volume": 100.0, "positionSide": "SHORT"}]
    c.symbol_leverage = lambda symbol=None: 20  # type: ignore
    posted: list[int] = []

    def _req(method, path, params=None, signed=False, **_k):
        if path == "/fapi/v1/leverage":
            posted.append(int(params.get("leverage") or 0))
            return {"leverage": params.get("leverage")}
        return {}

    c._request = _req  # type: ignore
    # Live force query returns flat
    c.positions = lambda symbol=None, force=False, bypass_rest_cool=False: []  # type: ignore
    ok = c.ensure_exchange_leverage("EDUUSDT", 5)
    _row(
        "LEV_RESET_IGNORES_STICKY_GHOST",
        "POST leverage=5 when force positions empty",
        f"ok={ok} posted={posted}",
        ok is True and posted == [5],
    )


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
    test_resolve_fill_via_query_not_invent()
    test_resolve_fill_unverified_no_invent()
    test_close_succeeded_exchange_flat_wins()
    test_incomplete_close_always_safe_mode()
    test_reset_leverage_if_flat_marker()
    test_ensure_leverage_ignores_sticky_ghost()
    test_pending_verify_not_cached_as_closed()
    print("test_execution_discipline: ALL OK")
