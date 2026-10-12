#!/usr/bin/env python3
"""Phase 1+2 forensic baseline: production version, config (no secrets), open book, Sep vs Oct metrics."""
from __future__ import annotations

import json
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
OUT = Path(__file__).resolve().parent / "_forensic-master-baseline.json"

REMOTE = r'''
import json, os, time, re, gzip, subprocess
from collections import Counter, defaultdict
from pathlib import Path
from glob import glob
import urllib.request

tok = open("/etc/bilshenz.env").read().split("BRIDGE_TOKEN=")[1].splitlines()[0].strip().strip('"').strip("'")
H = {"Authorization": "Bearer " + tok}

def get(path):
    req = urllib.request.Request("http://127.0.0.1:8766" + path, headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

h = json.loads(urllib.request.urlopen("http://127.0.0.1:8766/health", timeout=8).read())
sc = h.get("scanner") or {}
st = get("/api/status")
pos = get("/api/positions")
acct = st.get("account") or {}
opens = [p for p in (pos.get("positions") or []) if abs(float(p.get("volume") or p.get("positionAmt") or 0)) > 1e-12]

# Git / deploy markers on VPS
py = Path("/opt/bilshenz/binance_trading_system/python")
def sha_file(p):
    try:
        import hashlib
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()[:16]
    except Exception as e:
        return str(e)

# Env keys only (no values that look like secrets)
env_text = Path("/etc/bilshenz.env").read_text(encoding="utf-8", errors="replace")
env_keys = []
for line in env_text.splitlines():
    line=line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k = line.split("=",1)[0].strip()
    if any(x in k.upper() for x in ("SECRET","TOKEN","KEY","PASS","AUTH")):
        env_keys.append(k + "=<redacted>")
    else:
        v = line.split("=",1)[1].strip().strip('"').strip("'")
        if len(v) > 80:
            v = v[:40] + "..."
        env_keys.append(f"{k}={v}")

import sys
sys.path.insert(0, str(py))
from frozen_strategy import assert_frozen_contract, frozen_contract_snapshot, LOCKED_PARTITION_USD
import momentum_scanner as ms
from leverage_policy import SHORT_LEVERAGE, LONG1_LEVERAGE

snap = assert_frozen_contract()

# Trade history
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

# Calendar map
cal_map = {}
days = cal.get("days") or cal
if isinstance(days, list):
    for row in days:
        dk = str(row.get("date") or row.get("day") or "")[:10]
        if dk:
            cal_map[dk] = {
                "pnl": float(row.get("pnl") or row.get("profit") or 0),
                "n": row.get("n") or row.get("trades") or row.get("fills"),
            }
elif isinstance(days, dict):
    for dk, v in days.items():
        dk = str(dk)[:10]
        if isinstance(v, dict):
            cal_map[dk] = {"pnl": float(v.get("pnl") or v.get("profit") or 0), "n": v.get("n") or v.get("fills")}
        else:
            cal_map[dk] = {"pnl": float(v or 0), "n": None}

# UI Sep baseline (authoritative when deal cache thin for early Sep)
UI_SEP = {
    "2026-09-23": {"pnl": 5.51, "fills": 4},
    "2026-09-24": {"pnl": 61.81, "fills": 32},
    "2026-09-25": {"pnl": 76.01, "fills": 38},
    "2026-09-26": {"pnl": -11.49, "fills": 38},
    "2026-09-27": {"pnl": 0.0, "fills": 0},
    "2026-09-28": {"pnl": 147.79, "fills": 12},
    "2026-09-29": {"pnl": 0.0, "fills": 14},
}

# Deal closed stats by day
by_day = defaultdict(lambda: {
    "closes": 0, "opens": 0, "pnl": 0.0, "wins": 0, "losses": 0,
    "gw": 0.0, "gl": 0.0, "short_pnl": 0.0, "long_pnl": 0.0,
    "abs_churn": 0.0, "quote_sum": 0.0, "quote_n": 0,
})
for d in deals:
    t = ts(d)
    if not t:
        continue
    dk = day_key(t)
    if dk < "2026-09-23" or dk > "2026-10-12":
        continue
    slot = by_day[dk]
    if d.get("is_close"):
        slot["closes"] += 1
        p = pnl(d)
        slot["pnl"] += p
        slot["abs_churn"] += abs(p)
        if p > 0:
            slot["wins"] += 1
            slot["gw"] += p
        elif p < 0:
            slot["losses"] += 1
            slot["gl"] += p
        side = str(d.get("position_side") or "").upper()
        if side == "SHORT":
            slot["short_pnl"] += p
        elif side == "LONG":
            slot["long_pnl"] += p
        q = float(d.get("quote_qty") or 0)
        if q > 0:
            slot["quote_sum"] += q
            slot["quote_n"] += 1
    else:
        slot["opens"] += 1

# Episodes MIX vs naked by era
def era_days(start, end):
    out = []
    for dk in sorted(by_day):
        if start <= dk <= end:
            out.append(dk)
    return out

eps = defaultdict(list)
for d in deals:
    if not d.get("is_close"):
        continue
    t = ts(d)
    dk = day_key(t)
    if dk < "2026-09-23" or dk > "2026-10-12":
        continue
    minute = time.strftime("%Y-%m-%d %H:%M", time.gmtime(t / 1000))
    eps[(dk, d.get("symbol"), minute)].append(d)

ep_era = defaultdict(lambda: {"mix_n": 0, "mix_pnl": 0.0, "naked_n": 0, "naked_pnl": 0.0})
for (dk, sym, minute), legs in eps.items():
    if dk <= "2026-09-28":
        era = "SEP_WINISH"
    elif dk <= "2026-09-30":
        era = "SEP_DRIFT"
    elif dk <= "2026-10-04":
        era = "OCT_EARLY"
    elif dk <= "2026-10-08":
        era = "OCT_CASCADE"
    else:
        era = "OCT_POSTFIX"
    sides = {str(x.get("position_side") or "").upper() for x in legs}
    net = sum(pnl(x) for x in legs)
    if "SHORT" in sides and "LONG" in sides:
        ep_era[era]["mix_n"] += 1
        ep_era[era]["mix_pnl"] += net
    elif "SHORT" in sides:
        ep_era[era]["naked_n"] += 1
        ep_era[era]["naked_pnl"] += net

# Aggregate helpers
def agg_days(dlist, prefer_cal=True):
    closes = pnl_s = wins = losses = gw = gl = abs_c = 0
    short_p = long_p = 0.0
    cal_pnl = 0.0
    cal_n = 0
    for dk in dlist:
        if prefer_cal and dk in UI_SEP:
            cal_pnl += UI_SEP[dk]["pnl"]
            cal_n += UI_SEP[dk]["fills"]
        elif dk in cal_map:
            cal_pnl += cal_map[dk]["pnl"]
            cal_n += int(cal_map[dk]["n"] or 0)
        s = by_day.get(dk)
        if not s:
            continue
        closes += s["closes"]
        pnl_s += s["pnl"]
        wins += s["wins"]
        losses += s["losses"]
        gw += s["gw"]
        gl += s["gl"]
        abs_c += s["abs_churn"]
        short_p += s["short_pnl"]
        long_p += s["long_pnl"]
    n_wl = wins + losses
    return {
        "days": dlist,
        "calendar_pnl": round(cal_pnl, 2),
        "calendar_fills": cal_n,
        "deal_closes": closes,
        "deal_pnl": round(pnl_s, 2),
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / n_wl, 4) if n_wl else None,
        "avg_win": round(gw / wins, 4) if wins else None,
        "avg_loss": round(gl / losses, 4) if losses else None,
        "gross_profit": round(gw, 2),
        "gross_loss": round(gl, 2),
        "profit_factor": round(gw / abs(gl), 4) if gl < 0 else None,
        "abs_churn": round(abs_c, 2),
        "short_pnl": round(short_p, 2),
        "long_pnl": round(long_p, 2),
        "avg_closes_per_day": round(closes / max(len(dlist), 1), 2),
    }

# Matched windows
# Sep 23-28 win window vs Oct 1-6 (6 calendar days) and Oct 7-12
sep_win = ["2026-09-23","2026-09-24","2026-09-25","2026-09-26","2026-09-27","2026-09-28"]
oct_1_6 = [f"2026-10-0{i}" for i in range(1,7)]
oct_7_12 = ["2026-10-07","2026-10-08","2026-10-09","2026-10-10","2026-10-11","2026-10-12"]
oct_1_12 = [f"2026-10-{i:02d}" for i in range(1,13)]

# Log exit reasons Sep26+ (available) and Oct eras
close_re = re.compile(r"(2026-09-2[3-9]|2026-09-30|2026-10-\d{2})T[^\s]+ .*scanner closed ([A-Z0-9]+USDT) reason=([A-Z0-9_]+)")
reasons_by_era = defaultdict(Counter)
files = ["/var/log/bilshenz/app.log"] + sorted(glob("/var/log/bilshenz/app.log.*.gz"))[:12]
for fp in files:
    try:
        fh = gzip.open(fp, "rt", encoding="utf-8", errors="replace") if fp.endswith(".gz") else open(fp, encoding="utf-8", errors="replace")
    except Exception:
        continue
    with fh:
        for line in fh:
            m = close_re.search(line)
            if not m:
                continue
            dk = m.group(1)
            reason = m.group(3)
            if dk <= "2026-09-28":
                era = "SEP_WINISH"
            elif dk <= "2026-09-30":
                era = "SEP_DRIFT"
            elif dk <= "2026-10-04":
                era = "OCT_EARLY"
            elif dk <= "2026-10-08":
                era = "OCT_CASCADE"
            else:
                era = "OCT_POSTFIX"
            reasons_by_era[era][reason] += 1

# Violation markers Oct
viol_pats = {
    "SAFE_MODE": re.compile(r"SAFE_MODE"),
    "rule_kernel": re.compile(r"rule_kernel|KERNEL_"),
    "ERR_4005": re.compile(r"-4005"),
    "ERR_4131": re.compile(r"-4131"),
    "ERR_2022": re.compile(r"-2022"),
    "INSTANT_FLATTEN": re.compile(r"instant.?flatten|max_wait_s=0", re.I),
    "defer_SHORT_TP": re.compile(r"defer SHORT_TP"),
    "positions_unavailable": re.compile(r"positions unavailable|PositionsUnavailable"),
    "SHORT_GONE": re.compile(r"SHORT_GONE"),
}
viol_by_era = defaultdict(Counter)
day_re = re.compile(r"(2026-09-2[3-9]|2026-09-30|2026-10-\d{2})T")
for fp in files[:6]:
    try:
        fh = gzip.open(fp, "rt", encoding="utf-8", errors="replace") if fp.endswith(".gz") else open(fp, encoding="utf-8", errors="replace")
    except Exception:
        continue
    with fh:
        for line in fh:
            m = day_re.search(line)
            if not m:
                continue
            dk = m.group(1)
            if dk <= "2026-09-28":
                era = "SEP_WINISH"
            elif dk <= "2026-09-30":
                era = "SEP_DRIFT"
            elif dk <= "2026-10-04":
                era = "OCT_EARLY"
            elif dk <= "2026-10-08":
                era = "OCT_CASCADE"
            else:
                era = "OCT_POSTFIX"
            for name, pat in viol_pats.items():
                if pat.search(line):
                    viol_by_era[era][name] += 1

# systemctl / clock
try:
    units = subprocess.check_output(["systemctl", "is-active", "bilshenz-binance-api", "bilshenz-forward-bot"], text=True).strip().splitlines()
except Exception as e:
    units = [str(e)]

out = {
    "phase1_baseline": {
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "server_local": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "mode": h.get("mode"),
        "testnet": st.get("testnet"),
        "connected": h.get("connected"),
        "balance": acct.get("balance"),
        "floating_profit": acct.get("profit"),
        "partition_usd": sc.get("partition_usd"),
        "can_execute": sc.get("can_execute"),
        "halt": sc.get("user_exec_halted"),
        "min_quote_vol_24h": sc.get("min_quote_vol_24h"),
        "volume_map_ready": sc.get("volume_map_ready"),
        "strategy_id": snap.get("strategy_id"),
        "frozen_ops": snap.get("ops"),
        "knobs": {
            "GAIN": ms.GAIN_THRESHOLD_PCT,
            "RETRACE": ms.RETRACE_ENTRY_PCT,
            "L1": ms.LONG1_ADVERSE_PCT,
            "L2": ms.LONG2_ADVERSE_PCT,
            "INV": ms.PAIR_INVALIDATION_PCT,
            "SHORT_TP": ms.SHORT_TP_PCT,
            "SMART": ms.SMART_EXIT_NET_PCT,
            "SHORT_LEV": SHORT_LEVERAGE,
            "LONG_LEV": LONG1_LEVERAGE,
            "MIN_VOL": ms.MIN_QUOTE_VOL_24H,
            "ENTRY_COOL_MS": ms.ENTRY_COOLDOWN_MS,
            "EPISODE_COOL_MS": ms.EPISODE_COOLDOWN_MS,
            "INV_COOL_MS": ms.INVALIDATION_COOLDOWN_MS,
            "SETTLE_MS": ms.LONG_ENTRY_DELAY_MS,
        },
        "file_sha16": {
            "momentum_scanner.py": sha_file(py / "momentum_scanner.py"),
            "frozen_strategy.py": sha_file(py / "frozen_strategy.py"),
            "binance_connector.py": sha_file(py / "binance_connector.py"),
            "main.py": sha_file(py / "main.py"),
        },
        "units_active": units,
        "open_n": len(opens),
        "opens": [
            {
                "symbol": p.get("symbol"),
                "side": p.get("positionSide") or p.get("type"),
                "qty": p.get("volume"),
                "ui_lev": p.get("leverage"),
                "ex_lev": p.get("exchange_leverage"),
                "pnl": p.get("profit"),
                "entry": p.get("entryPrice") or p.get("price_open"),
                "mark": p.get("markPrice"),
            }
            for p in opens
        ],
        "env_keys_redacted": env_keys[:80],
        "rule_kernel_absent": not (py / "rule_kernel.py").exists(),
        "evidence_limits": [
            "Deal cache thin/absent for Sep 23-25 closes (UI calendar used for those days)",
            "MAE/MFE per trade not stored in deal cache — unavailable without tick reconstruction",
            "Funding fees not separated in deal cache profit field",
            "October incomplete month — use matched windows not full-month vs 12 days raw",
        ],
    },
    "phase2_windows": {
        "sep_23_28": agg_days(sep_win),
        "oct_1_6": agg_days(oct_1_6),
        "oct_7_12": agg_days(oct_7_12),
        "oct_1_12": agg_days(oct_1_12),
        "ui_sep": UI_SEP,
        "calendar_oct": {k: cal_map[k] for k in sorted(cal_map) if k.startswith("2026-10")},
        "deal_days": {
            dk: {
                "closes": v["closes"], "pnl": round(v["pnl"], 2),
                "wins": v["wins"], "losses": v["losses"],
                "gw": round(v["gw"], 2), "gl": round(v["gl"], 2),
                "abs_churn": round(v["abs_churn"], 2),
                "short_pnl": round(v["short_pnl"], 2),
                "long_pnl": round(v["long_pnl"], 2),
            }
            for dk, v in sorted(by_day.items())
        },
    },
    "episodes_by_era": {k: {kk: (round(vv, 2) if isinstance(vv, float) else vv) for kk, vv in v.items()} for k, v in ep_era.items()},
    "close_reasons_by_era": {k: dict(v) for k, v in reasons_by_era.items()},
    "violation_markers_by_era": {k: dict(v) for k, v in viol_by_era.items()},
}
print(json.dumps(out))
'''


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", key_filename=str(KEY), timeout=40)
    sftp = c.open_sftp()
    with sftp.file("/tmp/_forensic-master-baseline.py", "w") as f:
        f.write(REMOTE)
    sftp.close()
    _, o, e = c.exec_command(
        "/opt/bilshenz/binance_trading_system/python/.venv/bin/python /tmp/_forensic-master-baseline.py",
        timeout=300,
    )
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    c.close()
    if err.strip():
        print("STDERR", err[-2000:])
    data = json.loads(out)
    OUT.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("WROTE", OUT)
    b = data["phase1_baseline"]
    print("UTC", b["utc"], "mode", b["mode"], "testnet", b["testnet"], "bal", b["balance"], "part", b["partition_usd"])
    print("OPEN", b["open_n"], b["opens"])
    print("KNOBS", b["knobs"])
    print("SHA", b["file_sha16"])
    print("--- WINDOWS ---")
    for name, w in data["phase2_windows"].items():
        if name in ("ui_sep", "calendar_oct", "deal_days"):
            continue
        print(name, "cal", w["calendar_pnl"], "fills", w["calendar_fills"],
              "deal_pnl", w["deal_pnl"], "closes", w["deal_closes"],
              "WR", w["win_rate"], "PF", w["profit_factor"], "churn", w["abs_churn"])
    print("EPISODES", data["episodes_by_era"])
    print("REASONS", data["close_reasons_by_era"])
    print("VIOLS", {k: {kk: vv for kk, vv in v.items() if vv} for k, v in data["violation_markers_by_era"].items()})


if __name__ == "__main__":
    main()
