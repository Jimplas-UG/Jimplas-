#!/usr/bin/env python3
"""Fact-check FRA desk vs Sep 23–25 contract after balance reset."""
from __future__ import annotations

from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set -e
export PYTHONIOENCODING=utf-8
PY=/opt/bilshenz/binance_trading_system/python/.venv/bin/python
TOK=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
cd /opt/bilshenz/binance_trading_system/python

echo "=== SERVICES ==="
systemctl is-active bilshenz-binance-api bilshenz-forward-bot

echo "=== LIVE ==="
$PY - <<'PY'
import json, urllib.request, inspect, os
from pathlib import Path

tok = open("/etc/bilshenz.env").read().split("BRIDGE_TOKEN=")[1].splitlines()[0].strip().strip('"').strip("'")
H = {"Authorization": "Bearer " + tok}

def get(path):
    req = urllib.request.Request("http://127.0.0.1:8766" + path, headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=20).read())

h = json.loads(urllib.request.urlopen("http://127.0.0.1:8766/health", timeout=8).read())
sc = h.get("scanner") or {}
st = get("/api/status")
pos = get("/api/positions")
acct = st.get("account") or {}
items = [p for p in (pos.get("positions") or []) if abs(float(p.get("volume") or p.get("positionAmt") or 0)) > 1e-12]

print("mode", h.get("mode"), "connected", h.get("connected"), "testnet", st.get("testnet"))
print("balance", acct.get("balance"), "profit", acct.get("profit"))
print("can_execute", sc.get("can_execute"), "halt", sc.get("user_exec_halted"), "exec_enabled", sc.get("exec_enabled") or st.get("exec_enabled"))
print("live_partition_usd", sc.get("partition_usd"), "partition_usd_locked", sc.get("partition_usd_locked"))
print("strategy", sc.get("strategy_id") or sc.get("frozen_strategy_id"))
print("last_exec_error", sc.get("last_exec_error"))
print("open_n", len(items), "rest_cool_s", pos.get("rest_cool_s"), "stale", pos.get("stale"))
for p in items:
    print(
        "leg",
        p.get("symbol"),
        p.get("positionSide") or p.get("leg"),
        "qty",
        p.get("volume"),
        "ui_lev",
        p.get("leverage"),
        "ex_lev",
        p.get("exchange_leverage"),
        "pnl",
        p.get("profit"),
    )

from frozen_strategy import (
    assert_frozen_contract,
    LOCKED_PARTITION_USD,
    SMART_EXIT_NET_PCT,
    CLOSE_REST_COOL_MAX_WAIT_S,
    MANUAL_CLOSE_CONFIRM_REQUIRED,
    SMART_EXIT_REQUIRES_SHORT_PROFIT_IF_HEDGED,
)
import momentum_scanner as ms
import leverage_policy as lev
from binance_connector import BinanceConnector

snap = assert_frozen_contract()
print("FROZEN", snap["strategy_id"], "ops_partition", snap["ops"]["partition_usd"])
print("LOCKED_PARTITION_USD", LOCKED_PARTITION_USD)
print("SMART_EXIT_NET_PCT", SMART_EXIT_NET_PCT, "short_profit_if_hedged", SMART_EXIT_REQUIRES_SHORT_PROFIT_IF_HEDGED)
print("CLOSE_REST_COOL_MAX_WAIT_S", CLOSE_REST_COOL_MAX_WAIT_S)
print("MANUAL_CLOSE_CONFIRM_REQUIRED", MANUAL_CLOSE_CONFIRM_REQUIRED)
print("gain", ms.GAIN_THRESHOLD_PCT, "retrace", ms.RETRACE_ENTRY_PCT)
print("L1", ms.LONG1_ADVERSE_PCT, "L2", ms.LONG2_ADVERSE_PCT, "inv", float(ms.PAIR_INVALIDATION_PCT))
print("TP_short", ms.SHORT_TP_PCT, "TP_long", ms.LONG_TP_PCT, "hedge_pullback", float(ms.LONG_HEDGE_PULLBACK_PCT))
print("trail_floor", float(ms.SHORT_TRAIL_PULLBACK_PCT))
print("lev", lev.SHORT_LEVERAGE, lev.LONG1_LEVERAGE, lev.LONG2_LEVERAGE)
print("parts", float(ms.SHORT_PARTITION_PCT), float(ms.LONG1_PARTITION_PCT), float(ms.LONG2_PARTITION_PCT))
print("scanner_locked_usd", float(ms.LOCKED_PARTITION_USD), "PARTITION_USD_LOCKED", bool(ms.PARTITION_USD_LOCKED))

cool_src = inspect.getsource(BinanceConnector._wait_or_clear_cool_for_close)
print("close_cool_default_12s", "max_wait_s: float = 12.0" in cool_src)
print("has_rest_cooling_left", hasattr(BinanceConnector, "rest_cooling_left"))
print("rule_kernel_file", os.path.exists("rule_kernel.py"))
ms_src = Path("momentum_scanner.py").read_text(encoding="utf-8")
print("short_ok_for_smart", "short_ok_for_smart" in ms_src)
print("paired_underwater_hold", "_short_underwater" in ms_src)

risk = Path("/var/lib/bilshenz/scanner-risk.json")
raw = json.loads(risk.read_text()) if risk.exists() else {}
print(
    "risk_file",
    {
        k: raw.get(k)
        for k in (
            "partition_usd",
            "partition_usd_locked",
            "locked",
            "exec_halted",
            "short_pct",
            "long1_pct",
            "long2_pct",
        )
    },
)

# Pass/fail vs Sep23 facts
checks = []
checks.append(("strategy_short_first_v1", snap["strategy_id"] == "short_first_v1"))
checks.append(("partition_100_not_5000", abs(float(sc.get("partition_usd") or 0) - 100.0) < 1e-9))
checks.append(("partition_locked", bool(sc.get("partition_usd_locked")) or bool(ms.PARTITION_USD_LOCKED)))
checks.append(("balance_near_5000", abs(float(acct.get("balance") or 0) - 5000.0) < 50.0 or float(acct.get("balance") or 0) > 4500))
checks.append(("gain_5", abs(ms.GAIN_THRESHOLD_PCT - 5.0) < 1e-9))
checks.append(("retrace_0_7", abs(ms.RETRACE_ENTRY_PCT - 0.7) < 1e-9))
checks.append(("L1_2", abs(ms.LONG1_ADVERSE_PCT - 2.0) < 1e-9))
checks.append(("L2_4", abs(ms.LONG2_ADVERSE_PCT - 4.0) < 1e-9))
checks.append(("inv_6_5", abs(float(ms.PAIR_INVALIDATION_PCT) - 6.5) < 1e-9))
checks.append(("TP_2_5", abs(ms.SHORT_TP_PCT - 2.5) < 1e-9))
checks.append(("SMART_6", abs(float(SMART_EXIT_NET_PCT) - 6.0) < 1e-9))
checks.append(("lev_5_10", lev.SHORT_LEVERAGE == 5 and lev.LONG1_LEVERAGE == 10))
checks.append(("parts_50_40_40", abs(float(ms.SHORT_PARTITION_PCT) - 50) < 1e-6 and abs(float(ms.LONG1_PARTITION_PCT) - 40) < 1e-6))
checks.append(("close_cool_12", abs(float(CLOSE_REST_COOL_MAX_WAIT_S) - 12.0) < 1e-9))
checks.append(("manual_confirm", MANUAL_CLOSE_CONFIRM_REQUIRED is True))
checks.append(("smart_needs_short_profit", SMART_EXIT_REQUIRES_SHORT_PROFIT_IF_HEDGED is True))
checks.append(("no_rule_kernel", not os.path.exists("rule_kernel.py")))
checks.append(("can_execute", bool(sc.get("can_execute")) and not sc.get("user_exec_halted")))
checks.append(("connected", bool(h.get("connected"))))

print("=== CHECKS ===")
fail = 0
for name, ok in checks:
    print(("PASS" if ok else "FAIL"), name)
    fail += 0 if ok else 1
print("SUMMARY", "OK" if fail == 0 else f"FAILED_{fail}", "total", len(checks))
PY
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err.encode("ascii", "replace").decode("ascii")[-800:])
    c.close()


if __name__ == "__main__":
    main()
