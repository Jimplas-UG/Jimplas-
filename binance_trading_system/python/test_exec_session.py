"""Verify scanner exec arms immediately when bridge session is linked (no live Binance)."""
from __future__ import annotations

import os
import sys

# Ensure local imports
sys.path.insert(0, os.path.dirname(__file__))

from binance_connector import BinanceConnector, BinanceConfig
from momentum_scanner import MomentumScanner


def _scanner(connector: BinanceConnector) -> MomentumScanner:
    s = MomentumScanner(connector=connector, get_testnet=lambda: connector.cfg.testnet)
    # Persisted FRA halt must not poison unit assertions.
    s._user_exec_halted = False
    return s


def test_disconnected_blocks_exec() -> None:
    c = BinanceConnector(BinanceConfig(paper=False, testnet=True))
    c.configure("", "", True)
    c._connected = False
    s = _scanner(c)
    ok, reason = s._order_session_ok()
    assert not ok, "expected block when logged out"
    # Auth-halt path may report awaiting_account_verify before key-missing.
    assert reason in (
        "api_key_missing",
        "binance_not_logged_in",
        "awaiting_account_verify",
        "EMERGENCY_STOP",  # only if persist raced; _scanner clears halt
    ), reason
    assert reason != "EMERGENCY_STOP", reason


def test_connected_keys_arm_exec() -> None:
    c = BinanceConnector(BinanceConfig(paper=False, testnet=True))
    c.configure("test_key", "test_secret", True)
    c._connected = True
    c.mark_signed_ready(reason="test")
    s = _scanner(c)
    os.environ.pop("FORWARD_DRY_RUN", None)
    os.environ["SCANNER_EXEC"] = "1"
    ok, reason = s._order_session_ok()
    assert ok, f"expected armed when _connected=True + signed_ready, got block={reason!r}"
    st = s.status()
    assert st["can_execute"] is True
    assert st.get("exec_block") in (None, "")


def test_emergency_stop_blocks() -> None:
    c = BinanceConnector(BinanceConfig(paper=False, testnet=True))
    c.configure("k", "s", True)
    c._connected = True
    c.mark_signed_ready(reason="test")
    s = _scanner(c)
    os.environ.pop("FORWARD_DRY_RUN", None)
    os.environ["SCANNER_EXEC"] = "1"
    ok, reason = s._order_session_ok()
    assert ok, reason
    s.set_exec_enabled(False)
    s._rule_halt_codes = ["NAKED_SHORT_AT_10X"]
    s._rule_halt_ts = 1.0
    ok, reason = s._order_session_ok()
    assert not ok
    assert reason == "EMERGENCY_STOP"
    st = s.status()
    assert st.get("user_exec_halted") is True
    assert st.get("can_execute") is False
    s.set_exec_enabled(True)
    ok, reason = s._order_session_ok()
    assert ok, reason
    st2 = s.status()
    assert st2.get("rule_kernel", {}).get("halt_codes") == []
    assert st2.get("rule_kernel", {}).get("halt_ts") in (None, 0, 0.0)


def test_forward_dry_run_blocks() -> None:
    c = BinanceConnector(BinanceConfig(paper=False, testnet=True))
    c.configure("k", "s", True)
    c._connected = True
    c.mark_signed_ready(reason="test")
    s = _scanner(c)
    os.environ["FORWARD_DRY_RUN"] = "1"
    os.environ["SCANNER_EXEC"] = "1"
    ok, reason = s._order_session_ok()
    assert not ok
    assert reason == "FORWARD_DRY_RUN"
    os.environ.pop("FORWARD_DRY_RUN", None)


if __name__ == "__main__":
    test_disconnected_blocks_exec()
    test_connected_keys_arm_exec()
    test_emergency_stop_blocks()
    test_forward_dry_run_blocks()
    print("test_exec_session: OK")
