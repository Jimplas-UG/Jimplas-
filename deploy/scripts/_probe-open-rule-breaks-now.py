#!/usr/bin/env python3
"""Probe live open book for frozen-rule violations right now."""
from pathlib import Path
import json

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

REMOTE = r'''
import json, time, urllib.request
from pathlib import Path

tok = open("/etc/bilshenz.env").read().split("BRIDGE_TOKEN=")[1].splitlines()[0].strip().strip('"').strip("'")
H = {"Authorization": "Bearer " + tok}

def get(path):
    req = urllib.request.Request("http://127.0.0.1:8766" + path, headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=25).read())

h = json.loads(urllib.request.urlopen("http://127.0.0.1:8766/health", timeout=8).read())
sc = h.get("scanner") or {}
st = get("/api/status")
pos = get("/api/positions")
acct = st.get("account") or {}
opens = [p for p in (pos.get("positions") or []) if abs(float(p.get("volume") or p.get("positionAmt") or 0)) > 1e-12]

print("UTC", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
print("LIVE mode", h.get("mode"), "testnet", h.get("testnet") or st.get("testnet"),
      "can", sc.get("can_execute"), "halt", sc.get("user_exec_halted"),
      "part", sc.get("partition_usd"), "bal", acct.get("balance"), "profit", acct.get("profit"))
print("OPEN_N", len(opens))

# Expected caps from locked $100 partition
PART = float(sc.get("partition_usd") or 100.0)
SHORT_NOTIONAL = PART * 0.50 * 5   # 250
LONG_LEG_NOTIONAL = PART * 0.40 * 10  # 400
LONG_STACK_NOTIONAL = LONG_LEG_NOTIONAL * 2  # 800

# Group by symbol
by_sym = {}
for p in opens:
    sym = str(p.get("symbol") or "?").upper()
    by_sym.setdefault(sym, []).append(p)

violations = []
for sym, legs in sorted(by_sym.items()):
    shorts = [p for p in legs if str(p.get("positionSide") or "").upper() == "SHORT"
              or (str(p.get("type") or "").upper() == "SELL" and str(p.get("positionSide") or "SHORT").upper() != "LONG")]
    longs = [p for p in legs if str(p.get("positionSide") or "").upper() == "LONG"
             or str(p.get("type") or "").upper() == "BUY"]
    print("---", sym, "legs", len(legs), "SHORT", len(shorts), "LONG", len(longs))
    for p in legs:
        side = str(p.get("positionSide") or p.get("type") or "?")
        qty = float(p.get("volume") or p.get("positionAmt") or 0)
        entry = float(p.get("entryPrice") or p.get("price_open") or 0)
        mark = float(p.get("markPrice") or p.get("mark") or 0)
        lev_ui = p.get("leverage")
        lev_ex = p.get("exchange_leverage")
        pnl = p.get("profit") or p.get("unRealizedProfit")
        notional = abs(qty) * (entry or mark or 0)
        print(f"  {side} qty={qty} entry={entry} mark={mark} ui_lev={lev_ui} ex_lev={lev_ex} notional={round(notional,2)} pnl={pnl}")

    # Rule checks
    if longs and not shorts:
        violations.append({"sym": sym, "rule": "ORPHAN_LONG", "detail": "LONG open without SHORT (forbidden)"})
    for p in shorts:
        qty = float(p.get("volume") or 0)
        entry = float(p.get("entryPrice") or p.get("price_open") or 0)
        notional = abs(qty) * entry if entry else 0
        lev = float(p.get("exchange_leverage") or p.get("leverage") or 0)
        if not longs and lev >= 9.5:
            violations.append({"sym": sym, "rule": "NAKED_SHORT_10X", "detail": f"naked short exchange/ui lev={lev} (must be 5x)"})
        if notional > SHORT_NOTIONAL * 1.25 + 1:
            violations.append({"sym": sym, "rule": "SHORT_OVERSIZE", "detail": f"short notional {round(notional,2)} > cap {SHORT_NOTIONAL*1.25}"})
    long_notional = 0.0
    for p in longs:
        qty = float(p.get("volume") or 0)
        entry = float(p.get("entryPrice") or p.get("price_open") or 0)
        long_notional += abs(qty) * entry if entry else 0
    if long_notional > LONG_STACK_NOTIONAL * 1.15 + 1:
        violations.append({"sym": sym, "rule": "LONG_OVERSIZE", "detail": f"long stack notional {round(long_notional,2)} > cap ~{LONG_STACK_NOTIONAL}"})
    # Adverse / invalidation if short+price known
    if shorts:
        sh = shorts[0]
        entry = float(sh.get("entryPrice") or sh.get("price_open") or 0)
        mark = float(sh.get("markPrice") or sh.get("mark") or 0)
        if entry > 0 and mark > 0:
            adverse = (mark - entry) / entry * 100.0
            print(f"  short_adverse_pct={round(adverse,3)}")
            if adverse >= 6.5:
                violations.append({"sym": sym, "rule": "PAST_INVALIDATION", "detail": f"adverse {round(adverse,2)}% >= 6.5% still open"})
            # L1 early if long exists and adverse < 2
            if longs and adverse + 1e-9 < 2.0:
                violations.append({"sym": sym, "rule": "LONG1_EARLY", "detail": f"LONG open while short adverse only {round(adverse,2)}% (<2%)"})

# Scanner coin state if available
try:
    scan = get("/api/scanner/status") if False else None
except Exception:
    scan = None
try:
    rows = get("/api/scanner")
except Exception:
    try:
        rows = st.get("scanner") or sc
    except Exception:
        rows = {}

# Try strategies / coins endpoint
coins = []
for path in ("/api/strategies", "/api/scanner/coins", "/api/status"):
    try:
        j = get(path) if path != "/api/status" else st
        if path == "/api/status":
            coins = j.get("strategies") or j.get("coins") or j.get("active") or []
        else:
            coins = j.get("strategies") or j.get("coins") or j.get("items") or (j if isinstance(j, list) else [])
        if coins:
            break
    except Exception:
        pass

active = []
if isinstance(coins, list):
    for c in coins:
        if not isinstance(c, dict):
            continue
        status = str(c.get("status") or "")
        if any(x in status for x in ("Short", "Long", "Pending")) and "Watch" not in status:
            active.append(c)
            print("SCANNER", c.get("symbol"), "status", status,
                  "adv_peak", c.get("short_adverse_peak_pct") or c.get("adverse_peak"),
                  "pnl", c.get("unrealized_pnl") or c.get("pnl"),
                  "short", bool(c.get("short") or c.get("has_short")),
                  "l1", bool(c.get("long1") or c.get("has_long1")),
                  "l2", bool(c.get("long2") or c.get("has_long2")))

print("VIOLATION_N", len(violations))
for v in violations:
    print("VIOLATION", v["sym"], v["rule"], v["detail"])

# Recent close reasons last 2h from app.log
import re
from collections import Counter
text = ""
try:
    text = Path("/var/log/bilshenz/app.log").read_text(encoding="utf-8", errors="replace")[-2_000_000:]
except Exception as e:
    print("LOG_ERR", e)
now = time.time()
# lines with defer SHORT_TP / SAFE_MODE / naked / paired hold
hits = Counter()
samples = []
for line in text.splitlines():
    if "2026-10-1" not in line:
        continue
    # last ~6h roughly by string date 10-10 / 10-11
    if not ("2026-10-10T2" in line or "2026-10-11" in line or "2026-10-10T1" in line):
        # keep broader today
        if "2026-10-10" not in line and "2026-10-11" not in line:
            continue
    for key in ("SAFE_MODE", "rule_kernel", "defer SHORT_TP", "NAKED", "paired hold",
                "long_residual_abort", "SHORT_GONE", "positions unavailable",
                "adopt SHORT refused", "LONG1_PULLBACK", "LONG2_PULLBACK",
                "reason=SHORT_TP", "reason=RESCUE", "reason=INVALIDATION",
                "exchange_leverage=10", "target=10"):
        if key.lower() in line.lower() or key in line:
            hits[key] += 1
            if key in ("defer SHORT_TP", "LONG1_PULLBACK", "adopt SHORT refused", "SAFE_MODE", "SHORT_GONE") and len(samples) < 12:
                samples.append(line[:220])
print("LOG_HITS_RECENT", dict(hits.most_common(20)))
for s in samples[:8]:
    print("SAMPLE", s)
'''


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", key_filename=str(KEY), timeout=25)
    sftp = c.open_sftp()
    with sftp.file("/tmp/_probe-open-rule-breaks-now.py", "w") as f:
        f.write(REMOTE)
    sftp.close()
    _, o, e = c.exec_command(
        "/opt/bilshenz/binance_trading_system/python/.venv/bin/python /tmp/_probe-open-rule-breaks-now.py",
        timeout=60,
    )
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[:1500])
    c.close()


if __name__ == "__main__":
    main()
