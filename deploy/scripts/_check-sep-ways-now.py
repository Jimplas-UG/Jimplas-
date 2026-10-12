#!/usr/bin/env python3
"""Live Sep23-ways scorecard: contract, knobs, opens, last 48h rule hits, episode mix."""
from pathlib import Path
import json

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
OUT = Path(__file__).resolve().parent / "_check-sep-ways-now.json"

REMOTE = r'''
import json, re, time, gzip
from collections import Counter, defaultdict
from pathlib import Path
from glob import glob
import urllib.request

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

# Live contract from process modules
import sys
sys.path.insert(0, "/opt/bilshenz/binance_trading_system/python")
from frozen_strategy import assert_frozen_contract, LOCKED_PARTITION_USD
from leverage_policy import symbol_exchange_leverage, SHORT_LEVERAGE
import momentum_scanner as ms

snap = assert_frozen_contract()
checks = []

def ok(name, cond, detail=""):
    checks.append({"name": name, "ok": bool(cond), "detail": detail})

ok("strategy_id", snap["strategy_id"] == "short_first_v1", snap["strategy_id"])
ok("partition_100", abs(float(sc.get("partition_usd") or 0) - 100) < 1e-9, str(sc.get("partition_usd")))
ok("partition_locked_const", abs(LOCKED_PARTITION_USD - 100) < 1e-9)
ok("can_execute", sc.get("can_execute") is True, str(sc.get("can_execute")))
ok("not_halted", not sc.get("user_exec_halted"), str(sc.get("user_exec_halted")))
ok("no_rule_kernel_file", not Path("/opt/bilshenz/binance_trading_system/python/rule_kernel.py").exists())
ok("no_SAFE_MODE_in_scanner", "SAFE_MODE" not in Path("/opt/bilshenz/binance_trading_system/python/momentum_scanner.py").read_text(encoding="utf-8"))
ok("naked_lev_5", symbol_exchange_leverage(has_recovery_long=False) == 5)
ok("hedged_lev_10", symbol_exchange_leverage(has_recovery_long=True) == 10)
ok("min_vol_10m", float(ms.MIN_QUOTE_VOL_24H) >= 10_000_000, str(ms.MIN_QUOTE_VOL_24H))
ok("inv_cool_20m", int(ms.INVALIDATION_COOLDOWN_MS) >= 1_200_000)
ok("ep_cool_10m", int(ms.EPISODE_COOLDOWN_MS) >= 600_000)
ok("settle_3s", int(ms.LONG_ENTRY_DELAY_MS) >= 3000)
ok("hedged_tp_gate", hasattr(ms.MomentumScanner, "_hedged_short_exit_net_ok"))
ok("smart_exit_6", abs(float(ms.SMART_EXIT_NET_PCT) - 6.0) < 1e-9, str(ms.SMART_EXIT_NET_PCT))
ok("short_tp_2_5", abs(float(ms.SHORT_TP_PCT) - 2.5) < 1e-9)
ok("gain_5", abs(float(ms.GAIN_THRESHOLD_PCT) - 5.0) < 1e-9)
ok("retrace_0_7", abs(float(ms.RETRACE_ENTRY_PCT) - 0.7) < 1e-9)
ok("l1_2", abs(float(ms.LONG1_ADVERSE_PCT) - 2.0) < 1e-9)
ok("l2_4", abs(float(ms.LONG2_ADVERSE_PCT) - 4.0) < 1e-9)
ok("inv_6_5", abs(float(ms.PAIR_INVALIDATION_PCT) - 6.5) < 1e-9)

# Open legs size/leverage vs partition
size_breaks = []
for p in opens:
    sym = p.get("symbol")
    side = str(p.get("positionSide") or p.get("type") or "").upper()
    qty = float(p.get("volume") or p.get("positionAmt") or 0)
    px = float(p.get("markPrice") or p.get("entryPrice") or p.get("price_open") or 0)
    notional = abs(qty * px)
    ui_lev = p.get("leverage")
    ex_lev = p.get("exchange_leverage")
    is_short = side in ("SHORT", "SELL")
    # short ~250, long leg ~400, stacked longs ~800
    if is_short and notional > 320:
        size_breaks.append({"sym": sym, "side": side, "notional": round(notional, 2), "ui": ui_lev, "ex": ex_lev})
    if (not is_short) and notional > 900:
        size_breaks.append({"sym": sym, "side": side, "notional": round(notional, 2), "ui": ui_lev, "ex": ex_lev})
    if is_short and ex_lev is not None and int(float(ex_lev)) != 5 and not any(
        str(x.get("positionSide") or "").upper() == "LONG" or str(x.get("type") or "").upper() == "BUY"
        for x in opens if x.get("symbol") == sym
    ):
        size_breaks.append({"sym": sym, "side": "NAKED_NOT_5X", "notional": round(notional, 2), "ui": ui_lev, "ex": ex_lev})

ok("open_size_ok", len(size_breaks) == 0, json.dumps(size_breaks[:5]))

# Deal cache last 48h
raw = json.loads(Path("/var/lib/bilshenz/trade-history-cache.json").read_text(encoding="utf-8"))
deals = raw.get("deals") or []
cal = raw.get("calendar") or {}

def ts(d):
    v = d.get("time") or d.get("closeTime") or 0
    x = float(v or 0)
    return int(x if x > 1e12 else x * 1000)

def day_key(ms):
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000.0))

def pnl(d):
    return float(d.get("realized_pnl") or d.get("profit") or 0)

now_ms = int(time.time() * 1000)
cut48 = now_ms - 48 * 3600 * 1000
cut24 = now_ms - 24 * 3600 * 1000

closes_48 = [d for d in deals if d.get("is_close") and ts(d) >= cut48]
closes_24 = [d for d in deals if d.get("is_close") and ts(d) >= cut24]

# Episodes last 48h
eps = defaultdict(list)
for d in closes_48:
    t = ts(d)
    minute = time.strftime("%Y-%m-%d %H:%M", time.gmtime(t / 1000))
    eps[(d.get("symbol"), minute)].append(d)

mix_n = mix_pnl = naked_n = naked_pnl = 0.0
mix_n = naked_n = 0
for legs in eps.values():
    sides = {str(x.get("position_side") or "").upper() for x in legs}
    net = sum(pnl(x) for x in legs)
    if "SHORT" in sides and "LONG" in sides:
        mix_n += 1
        mix_pnl += net
    elif "SHORT" in sides:
        naked_n += 1
        naked_pnl += net

# Quote size breaks last 48h
q_breaks = []
for d in closes_48:
    q = float(d.get("quote_qty") or 0)
    side = str(d.get("position_side") or "").upper()
    if side == "SHORT" and q > 320:
        q_breaks.append((d.get("symbol"), day_key(ts(d)), q, pnl(d)))
    if side == "LONG" and q > 900:
        q_breaks.append((d.get("symbol"), day_key(ts(d)), q, pnl(d)))

ok("deal_size_48h_ok", len(q_breaks) == 0, str(q_breaks[:5]))

# Log markers last 48h (app.log + recent gz)
day_re = re.compile(r"(2026-10-1[01])T")
PATS = {
    "SAFE_MODE": re.compile(r"SAFE_MODE"),
    "rule_kernel": re.compile(r"rule_kernel|KERNEL_"),
    "ERR_4005": re.compile(r"-4005"),
    "ERR_4131": re.compile(r"-4131"),
    "INSTANT_FLATTEN": re.compile(r"instant.?flatten|max_wait_s=0|immediate flatten", re.I),
    "naked_10x": re.compile(r"naked.*10|force.*10x", re.I),
    "SHORT_GONE": re.compile(r"SHORT_GONE"),
    "defer_SHORT_TP": re.compile(r"defer SHORT_TP"),
    "LONG1_PULLBACK": re.compile(r"reason=LONG1_PULLBACK|LONG1_PULLBACK"),
    "SOLO_BLOCK": re.compile(r"paired hold blocks solo|paired hold keeps"),
    "RESCUE": re.compile(r"reason=RESCUE"),
    "SHORT_TP": re.compile(r"reason=SHORT_TP"),
    "INVALIDATION": re.compile(r"reason=INVALIDATION"),
    "SMART_EXIT": re.compile(r"SMART_EXIT|reason=SMART_EXIT"),
    "positions_unavailable": re.compile(r"positions unavailable|PositionsUnavailable"),
    "ERR_429": re.compile(r"REST cooling|429"),
}
counts = Counter()
close_reasons = Counter()
close_re = re.compile(r"scanner closed ([A-Z0-9]+USDT) reason=([A-Z0-9_]+)")

files = ["/var/log/bilshenz/app.log"] + sorted(glob("/var/log/bilshenz/app.log.*.gz"))[:3]
for fp in files:
    try:
        fh = gzip.open(fp, "rt", encoding="utf-8", errors="replace") if fp.endswith(".gz") else open(fp, "r", encoding="utf-8", errors="replace")
    except Exception:
        continue
    with fh:
        for line in fh:
            if "2026-10-10" not in line and "2026-10-11" not in line:
                continue
            # only last ~48h roughly via date
            for name, pat in PATS.items():
                if pat.search(line):
                    counts[name] += 1
            m = close_re.search(line)
            if m:
                close_reasons[m.group(2)] += 1

# Violation-style hits that must be ZERO
ok("no_SAFE_MODE_logs", counts.get("SAFE_MODE", 0) == 0, str(counts.get("SAFE_MODE", 0)))
ok("no_rule_kernel_logs", counts.get("rule_kernel", 0) == 0, str(counts.get("rule_kernel", 0)))
ok("no_instant_flatten", counts.get("INSTANT_FLATTEN", 0) == 0, str(counts.get("INSTANT_FLATTEN", 0)))
ok("no_naked_10x_logs", counts.get("naked_10x", 0) == 0, str(counts.get("naked_10x", 0)))

# Calendar recent
cal_days = {}
days = cal.get("days") or cal
if isinstance(days, list):
    for row in days:
        dk = str(row.get("date") or row.get("day") or "")[:10]
        if dk >= "2026-10-09":
            cal_days[dk] = {"pnl": float(row.get("pnl") or row.get("profit") or 0), "n": row.get("n") or row.get("fills")}
elif isinstance(days, dict):
    for dk, v in days.items():
        if str(dk) >= "2026-10-09":
            cal_days[str(dk)[:10]] = v if isinstance(v, dict) else {"pnl": v}

sep_baseline = {
    "2026-09-23": 5.51, "2026-09-24": 61.81, "2026-09-25": 76.01,
    "2026-09-26": -11.49, "2026-09-28": 147.79,
}

out = {
    "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "mode": h.get("mode"),
    "testnet": st.get("testnet"),
    "connected": h.get("connected"),
    "balance": acct.get("balance"),
    "profit": acct.get("profit"),
    "partition": sc.get("partition_usd"),
    "can_execute": sc.get("can_execute"),
    "halt": sc.get("user_exec_halted"),
    "min_vol": sc.get("min_quote_vol_24h"),
    "vol_ready": sc.get("volume_map_ready"),
    "open_n": len(opens),
    "opens": [
        {
            "sym": p.get("symbol"),
            "side": p.get("positionSide") or p.get("type"),
            "qty": p.get("volume"),
            "ui_lev": p.get("leverage"),
            "ex_lev": p.get("exchange_leverage"),
            "pnl": p.get("profit"),
            "notional": round(abs(float(p.get("volume") or 0) * float(p.get("markPrice") or p.get("entryPrice") or 0)), 2),
        }
        for p in opens
    ],
    "checks": checks,
    "pass_n": sum(1 for c in checks if c["ok"]),
    "fail_n": sum(1 for c in checks if not c["ok"]),
    "pnl_24h_deals": round(sum(pnl(d) for d in closes_24), 2),
    "pnl_48h_deals": round(sum(pnl(d) for d in closes_48), 2),
    "closes_24": len(closes_24),
    "closes_48": len(closes_48),
    "episodes_48h": {
        "mix_n": mix_n, "mix_pnl": round(mix_pnl, 2),
        "naked_n": naked_n, "naked_pnl": round(naked_pnl, 2),
    },
    "close_reasons_oct10_11": dict(close_reasons),
    "log_counts_oct10_11": dict(counts),
    "calendar_recent": cal_days,
    "sep_baseline": sep_baseline,
    "sep_total": round(sum(sep_baseline.values()), 2),
}
print(json.dumps(out))
'''


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", key_filename=str(KEY), timeout=30)
    sftp = c.open_sftp()
    with sftp.file("/tmp/_check-sep-ways-now.py", "w") as f:
        f.write(REMOTE)
    sftp.close()
    _, o, e = c.exec_command(
        "cd /opt/bilshenz/binance_trading_system/python && .venv/bin/python /tmp/_check-sep-ways-now.py",
        timeout=180,
    )
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    c.close()
    if err.strip():
        print("STDERR", err[-1500:])
    data = json.loads(out)
    OUT.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("UTC", data["utc"])
    print("LIVE mode", data["mode"], "testnet", data["testnet"], "conn", data["connected"],
          "bal", data["balance"], "part", data["partition"], "can", data["can_execute"], "halt", data["halt"])
    print("OPEN_N", data["open_n"])
    for p in data["opens"]:
        print("  OPEN", p)
    print("SCORE", data["pass_n"], "/", data["pass_n"] + data["fail_n"])
    for c in data["checks"]:
        mark = "PASS" if c["ok"] else "FAIL"
        print(f"  {mark} {c['name']}", c.get("detail") or "")
    print("PnL deals 24h", data["pnl_24h_deals"], "n", data["closes_24"],
          "| 48h", data["pnl_48h_deals"], "n", data["closes_48"])
    print("Episodes 48h", data["episodes_48h"])
    print("Close reasons", data["close_reasons_oct10_11"])
    print("Log counts", {k: v for k, v in data["log_counts_oct10_11"].items() if v})
    print("Calendar recent", data["calendar_recent"])
    print("Sep baseline total", data["sep_total"], data["sep_baseline"])
    if data["fail_n"]:
        print("VERDICT VIOLATIONS_PRESENT")
    else:
        print("VERDICT NO_HARD_VIOLATIONS — following Sep locks")


if __name__ == "__main__":
    main()
