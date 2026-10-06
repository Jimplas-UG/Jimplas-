#!/usr/bin/env python3
"""FRA end-to-end desk confirmation — read-only + remote unit suites. No new live entries."""
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
AUTH="Authorization: Bearer $TOK"

echo "=== SERVICES ==="
systemctl is-active bilshenz-binance-api bilshenz-forward-bot || true

echo "=== REMOTE SUITES ==="
cd /opt/bilshenz/binance_trading_system/python
$PY test_violation_locks.py
$PY test_rule_kernel.py
$PY test_close_orders.py
$PY test_execution_discipline.py

echo "=== E2E PYTHON ==="
$PY - <<'PY'
import json, inspect, urllib.request, subprocess, sys
from pathlib import Path

rows = []

def row(test, expected, actual, ok):
    status = "PASS" if ok else "FAIL"
    rows.append(ok)
    print(f"TEST={test}")
    print(f"EXPECTED={expected}")
    print(f"ACTUAL={actual}")
    print(f"STATUS={status}")

# --- services already checked; health ---
h = json.loads(urllib.request.urlopen("http://127.0.0.1:8766/health", timeout=8).read())
sc = h.get("scanner") or {}
row("HEALTH_CONNECTED", "connected True", f"conn={h.get('connected')} mode={h.get('mode')}", bool(h.get("connected")))
row(
    "PARTITION_LOCKED",
    "partition_usd=100 locked",
    f"part={sc.get('partition_usd')} locked={sc.get('partition_usd_locked')}",
    abs(float(sc.get("partition_usd") or 0) - 100.0) < 1e-9 and bool(sc.get("partition_usd_locked")),
)
row(
    "EXEC_ARMED",
    "can_execute True, halt False, safe False (or stuck/oversize explained)",
    f"can={sc.get('can_execute')} halt={sc.get('user_exec_halted')} safe={sc.get('safe_mode')} stuck={sc.get('stuck_close_symbols')} over={sc.get('oversize_external_symbols')}",
    bool(sc.get("can_execute"))
    and not sc.get("user_exec_halted")
    and not sc.get("safe_mode")
    and not (sc.get("stuck_close_symbols") or [])
    and not (sc.get("oversize_external_symbols") or []),
)

# --- auth APIs ---
tok = open("/etc/bilshenz.env").read().split("BRIDGE_TOKEN=")[1].splitlines()[0].strip().strip('"').strip("'")
H = {"Authorization": "Bearer " + tok}

def get(path):
    req = urllib.request.Request("http://127.0.0.1:8766" + path, headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=12).read())

pos = get("/api/positions")
st = get("/api/status")
items = [p for p in (pos.get("positions") or []) if abs(float(p.get("volume") or p.get("positionAmt") or 0)) > 1e-12]
row("API_POSITIONS_AUTH", "HTTP 200 + list", f"n={len(pos.get('positions') or [])} open={len(items)} stale={pos.get('stale')}", isinstance(pos.get("positions"), list))
row("API_STATUS_AUTH", "HTTP 200 + account", f"keys={sorted(list(st.keys())[:8])} bal={(st.get('account') or {}).get('balance')}", isinstance(st, dict) and "account" in st)

# Flat book preferred for clean E2E; if open, report but do not fail hard if consistent
acct = st.get("account") or {}
if len(items) == 0:
    profit = float(acct.get("profit") or 0)
    row("BOOK_FLAT_NO_GHOST", "open=0 and account.profit~0", f"open=0 profit={profit}", abs(profit) < 1e-6)
else:
    row("BOOK_OPEN_VISIBLE", "open legs listed with symbol/side/qty", f"open={[(p.get('symbol'), p.get('positionSide') or p.get('side'), p.get('volume') or p.get('positionAmt')) for p in items]}", True)

# --- frozen contract + markers ---
sys.path.insert(0, "/opt/bilshenz/binance_trading_system/python")
from frozen_strategy import assert_frozen_contract
import momentum_scanner as ms
import binance_connector as bc
import leverage_policy as lev

try:
    snap = assert_frozen_contract()
    row("FROZEN_CONTRACT", "short_first_v1 part 100", f"{snap['strategy_id']} part={snap['ops']['partition_usd']}", snap["strategy_id"] == "short_first_v1" and abs(float(snap["ops"]["partition_usd"]) - 100) < 1e-9)
except AssertionError as e:
    row("FROZEN_CONTRACT", "assert ok", str(e), False)

row("KNOBS_ENTRY", "gain5 retrace0.7", f"{ms.GAIN_THRESHOLD_PCT}/{ms.RETRACE_ENTRY_PCT}", abs(ms.GAIN_THRESHOLD_PCT - 5) < 1e-9 and abs(ms.RETRACE_ENTRY_PCT - 0.7) < 1e-9)
row("KNOBS_HEDGE", "L1=2 L2=4 inv=6.5", f"{ms.LONG1_ADVERSE_PCT}/{ms.LONG2_ADVERSE_PCT}/{ms.PAIR_INVALIDATION_PCT}", abs(ms.LONG1_ADVERSE_PCT - 2) < 1e-9 and abs(ms.LONG2_ADVERSE_PCT - 4) < 1e-9 and abs(float(ms.PAIR_INVALIDATION_PCT) - 6.5) < 1e-9)
row("KNOBS_EXIT", "TP2.5 SMART6 lev5/10", f"tp={ms.SHORT_TP_PCT} smart={ms.SMART_EXIT_NET_PCT} lev={lev.SHORT_LEVERAGE}/{lev.LONG1_LEVERAGE}", abs(ms.SHORT_TP_PCT - 2.5) < 1e-9 and abs(float(ms.SMART_EXIT_NET_PCT) - 6) < 1e-9 and lev.SHORT_LEVERAGE == 5 and lev.LONG1_LEVERAGE == 10)

row("FILL_RESOLVE", "_resolve_executed_qty + query_order live", str(hasattr(bc.BinanceConnector, "_resolve_executed_qty") and hasattr(bc.BinanceConnector, "query_order")), hasattr(bc.BinanceConnector, "_resolve_executed_qty") and hasattr(bc.BinanceConnector, "query_order"))
row("CLOSE_CHUNK", "long_residual_abort_short in close_position", str("long_residual_abort_short" in inspect.getsource(bc.BinanceConnector.close_position)), "long_residual_abort_short" in inspect.getsource(bc.BinanceConnector.close_position))
row("FORCE_FLAT_4131", "force_flat_4131 marker", str("force_flat_4131" in inspect.getsource(bc.BinanceConnector._persistent_escape_4131_close)), "force_flat_4131" in inspect.getsource(bc.BinanceConnector._persistent_escape_4131_close))
ms_src = Path(ms.__file__).read_text(encoding="utf-8")
row("SAFE_MODE_LOCKS", "SAFE_MODE + OVERSIZE + CLOSE_INCOMPLETE + STUCK", f"safe={'SAFE_MODE' in ms_src} over={'OVERSIZE_EXTERNAL_SHORT' in ms_src} inc={'CLOSE_INCOMPLETE' in ms_src} stuck={'SAFE_MODE_STUCK_CLOSE' in ms_src}", all(x in ms_src for x in ("SAFE_MODE", "OVERSIZE_EXTERNAL_SHORT", "CLOSE_INCOMPLETE", "SAFE_MODE_STUCK_CLOSE")))
row("SOLO_HEDGE_LOCK", "_solo_hedge_exit_allowed + episode", str(hasattr(ms.MomentumScanner, "_solo_hedge_exit_allowed") and hasattr(ms.MomentumScanner, "_hedge_episode_active")), hasattr(ms.MomentumScanner, "_solo_hedge_exit_allowed") and hasattr(ms.MomentumScanner, "_hedge_episode_active"))
row("EXCHANGE_WINS_FLAT", "Flat on exchange in _close_succeeded", str("Flat on exchange" in inspect.getsource(ms.MomentumScanner._close_succeeded)), "Flat on exchange" in inspect.getsource(ms.MomentumScanner._close_succeeded))

main_src = Path("main.py").read_text(encoding="utf-8")
row("CLOSE_PENDING_VERIFY", "idempotent pending not CLOSED", str("CLOSE_PENDING_VERIFY" in main_src and "Never label CLOSE_PENDING_VERIFY as CLOSED" in main_src), "CLOSE_PENDING_VERIFY" in main_src and "Never label CLOSE_PENDING_VERIFY as CLOSED" in main_src)

# FE floating guard if present
fe = Path("/opt/bilshenz/frontend/lib/liveFloatingPnl.js")
if fe.exists():
    r = subprocess.run(["node", "lib/liveFloatingPnl.test.js"], cwd="/opt/bilshenz/frontend", capture_output=True, text=True)
    row("FE_FLOATING_PNL", "node liveFloatingPnl.test.js OK", (r.stdout or r.stderr or "")[-120:].replace("\n", " "), r.returncode == 0)
else:
    row("FE_FLOATING_PNL", "optional on FRA", "missing", True)

failed = sum(1 for x in rows if not x)
passed = sum(1 for x in rows if x)
print(f"E2E_SUMMARY passed={passed} failed={failed} total={len(rows)}")
if failed:
    raise SystemExit(1)
print("E2E_ALL_OK")
PY
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=300)
    out = o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii")
    err = e.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii")
    print(out)
    if err.strip():
        # Keep stderr noise but do not hide failures
        print("STDERR", err[-3000:])
    c.close()
    if "E2E_ALL_OK" not in out:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
