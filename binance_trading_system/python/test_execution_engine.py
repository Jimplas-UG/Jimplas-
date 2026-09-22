#!/usr/bin/env python3
"""Execution engine unit tests — validation, retry, duplicate prevention."""
from __future__ import annotations

import os
import sys
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(__file__))

os.environ["SCANNER_EXEC"] = "1"
os.environ.pop("FORWARD_DRY_RUN", None)

from execution_engine import ExecutionEngine, ExecutionSignal  # noqa: E402


class MockConnector:
    def __init__(self, *, paper: bool = False, api_key: str = "k") -> None:
        self.cfg = SimpleNamespace(paper=paper, api_key=api_key)
        self._connected = True
        self.calls: list[dict] = []
        self.fail_times = 0
        self.fail_with: dict | None = None

    def get_symbol_spec(self, symbol: str) -> dict:
        return {
            "symbol": symbol.upper(),
            "stepSize": 0.001,
            "minQty": 0.001,
            "minNotional": 5.0,
            "tickSize": 0.01,
        }

    def prepare_symbol_cached(self, symbol: str, leverage: int, margin_type: str = "ISOLATED") -> None:
        self.calls.append({"op": "prepare", "symbol": symbol, "lev": leverage})

    def ensure_exchange_leverage(self, symbol: str, leverage: int | None = None) -> bool:
        self.calls.append({"op": "ensure_lev", "symbol": symbol, "lev": leverage or 5})
        return True

    def _request(self, method: str, path: str, **kwargs):
        return {"availableBalance": 10000.0}

    def place_market_order(self, symbol, side, quantity, **kwargs) -> dict:
        self.calls.append({"op": "order", "symbol": symbol, "side": side, "qty": quantity, **kwargs})
        if self.fail_with:
            return dict(self.fail_with)
        if self.fail_times > 0:
            self.fail_times -= 1
            return {"ok": False, "error": "timeout", "retryable": True}
        return {
            "ok": True,
            "fill_price": 100.5,
            "quantity": quantity,
            "order_id": 12345,
            "latency_ms": 42.0,
        }

    def exchange_short_qty(self, symbol: str | None = None) -> float:
        return float(getattr(self, "_short_qty", 0.0))

    def ensure_hedge_mode(self) -> tuple[bool, str]:
        return True, ""

    def place_tp_market(self, symbol, entry_side, stop_price, quantity, **kwargs) -> dict:
        self.calls.append({"op": "tp", "symbol": symbol, "stop": stop_price})
        return {"ok": True, "order_id": 67890}


def _signal(**kw) -> ExecutionSignal:
    base = dict(
        symbol="TAGUSDT",
        side="SELL",
        quantity=10.0,
        reference_price=1.25,
        leverage=5,
        leg="SHORT",
        signal_id="test_sig_1",
        tp=1.20,
    )
    base.update(kw)
    return ExecutionSignal(**base)


def test_qualified_sell_executes() -> None:
    conn = MockConnector()
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    r = eng.execute(_signal(side="SELL"))
    assert r.ok, r.error
    assert r.order_id == 12345
    assert r.stage == "filled"
    events = eng.events()
    assert any(e["stage"] == "sending" for e in events)
    assert any(e["stage"] == "filled" for e in events)
    print("OK qualified SELL executes")


def test_recovery_long_buy_executes() -> None:
    """Short-first: recovery LONG1/LONG2 hedges are BUY orders and must pass."""
    conn = MockConnector()
    conn._short_qty = 10.0
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    r = eng.execute(_signal(side="BUY", leg="LONG1", tp=None))
    assert r.ok, r.error
    assert r.side == "BUY"
    r2 = eng.execute(_signal(side="BUY", leg="LONG2", tp=None, signal_id="buy_long2_1"))
    assert r2.ok, r2.error
    print("OK recovery LONG1/LONG2 BUY executes")


def test_standalone_buy_blocked_by_short_first() -> None:
    """Any BUY that is not a recovery long or a desk manual order must be blocked."""
    conn = MockConnector()
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    for leg in ("SHORT", "", "ENTRY"):
        r = eng.execute(
            _signal(side="BUY", leg=leg, tp=None, signal_id=f"buy_blocked_{leg or 'none'}")
        )
        assert not r.ok, f"BUY with leg={leg!r} must be blocked"
        assert r.error == "buy_blocked_short_first_policy"
        assert r.stage == "blocked_short_first"
    print("OK standalone BUY blocked by short-first policy")


def test_manual_buy_allowed() -> None:
    """Desk manual trading must allow BUY and SELL for speed/flexibility."""
    conn = MockConnector()
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    r = eng.execute(
        _signal(side="BUY", leg="MANUAL", tp=None, signal_id="buy_manual_1"),
        manual=True,
    )
    assert r.ok, r.error
    assert r.side == "BUY"
    print("OK manual BUY allowed")


def test_manual_orders_unique_client_ids() -> None:
    conn = MockConnector()
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    r1 = eng.execute(
        _signal(side="SELL", leg="MANUAL", tp=None, signal_id="MANUAL_X_SELL_1_100"),
        manual=True,
    )
    r2 = eng.execute(
        _signal(side="SELL", leg="MANUAL", tp=None, signal_id="MANUAL_X_SELL_1_101"),
        manual=True,
    )
    assert r1.ok and r2.ok
    assert r1.client_order_id != r2.client_order_id
    print("OK manual orders get unique client ids")


def test_tp_created() -> None:
    conn = MockConnector()
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    r = eng.execute(_signal())
    assert r.ok
    assert r.tp_order_id == 67890
    assert any(c["op"] == "tp" for c in conn.calls)
    print("OK TP created")


def test_invalid_quantity_blocked() -> None:
    conn = MockConnector()
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    r = eng.execute(_signal(quantity=0))
    assert not r.ok
    assert "invalid_quantity" in r.error or "quantity" in r.error
    print("OK invalid quantity handled")


def test_precision_min_notional() -> None:
    conn = MockConnector()
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    r = eng.execute(_signal(quantity=0.0001, reference_price=0.01))
    assert not r.ok
    assert "min_notional" in r.error or "quantity" in r.error
    print("OK precision/min notional handled")


def test_timeout_retry_works() -> None:
    conn = MockConnector()
    conn.fail_times = 2
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    t0 = time.perf_counter()
    r = eng.execute(_signal(signal_id="retry_test_1"))
    elapsed = (time.perf_counter() - t0) * 1000
    assert r.ok, r.error
    assert r.retry_count == 2
    assert elapsed >= 200
    print("OK timeout retry works")


def test_duplicate_prevention() -> None:
    conn = MockConnector()
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    sig = _signal(signal_id="dup_test_1")
    r1 = eng.execute(sig)
    r2 = eng.execute(sig)
    assert r1.ok
    assert not r2.ok
    assert r2.stage == "duplicate"
    print("OK duplicate prevention works")


def test_insufficient_margin() -> None:
    conn = MockConnector()
    conn._request = MagicMock(return_value={"availableBalance": 0.01})
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    r = eng.execute(_signal(signal_id="margin_test_1"))
    assert not r.ok
    assert "insufficient_margin" in r.error
    print("OK margin insufficient handled")


def test_forward_dry_run_blocks() -> None:
    os.environ["FORWARD_DRY_RUN"] = "1"
    conn = MockConnector()
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    r = eng.execute(_signal(signal_id="dry_test_1"))
    assert not r.ok
    assert r.error == "FORWARD_DRY_RUN"
    os.environ.pop("FORWARD_DRY_RUN", None)
    print("OK FORWARD_DRY_RUN blocks execution")


def test_primary_short_exchange_is_5x() -> None:
    conn = MockConnector()
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    r = eng.execute(_signal(side="SELL", leg="SHORT", leverage=20, signal_id="lev_short_1"))
    assert r.ok, r.error
    prep = [c for c in conn.calls if c.get("op") == "prepare"]
    assert prep and prep[-1]["lev"] == 5, "policy must force the primary short back to 5x"
    ensure = [c for c in conn.calls if c.get("op") == "ensure_lev"]
    assert ensure and ensure[-1]["lev"] == 5
    print("OK primary SHORT exchange leverage is 5x")


def test_recovery_long_exchange_is_10x() -> None:
    conn = MockConnector()
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    for leg, sig in (("LONG1", "lev_long1_1"), ("LONG2", "lev_long2_1")):
        conn.calls.clear()
        r = eng.execute(_signal(side="BUY", leg=leg, leverage=5, tp=None, signal_id=sig))
        assert r.ok, r.error
        prep = [c for c in conn.calls if c.get("op") == "prepare"]
        assert prep and prep[-1]["lev"] == 10, f"{leg} must be forced to 10x"
        ensure = [c for c in conn.calls if c.get("op") == "ensure_lev"]
        assert ensure and any(c["lev"] == 10 for c in ensure)
    print("OK recovery LONG1/LONG2 exchange leverage is 10x")


def test_latency_under_target_when_network_allows() -> None:
    conn = MockConnector()
    eng = ExecutionEngine(conn, session_ok=lambda: (True, ""))
    r = eng.execute(_signal(signal_id="lat_test_1"))
    assert r.ok
    assert r.latency_ms < 100
    print(f"OK execution latency {r.latency_ms}ms (mock)")


if __name__ == "__main__":
    tests = [
        test_qualified_sell_executes,
        test_recovery_long_buy_executes,
        test_standalone_buy_blocked_by_short_first,
        test_manual_buy_allowed,
        test_manual_orders_unique_client_ids,
        test_tp_created,
        test_invalid_quantity_blocked,
        test_precision_min_notional,
        test_timeout_retry_works,
        test_duplicate_prevention,
        test_insufficient_margin,
        test_forward_dry_run_blocks,
        test_primary_short_exchange_is_5x,
        test_recovery_long_exchange_is_10x,
        test_latency_under_target_when_network_allows,
    ]
    for t in tests:
        t()
    print("test_execution_engine: ALL OK")
