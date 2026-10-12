#!/usr/bin/env python3
"""Full Sep→Oct mistake catalog: PnL, episode mix, log rule hits, eras."""
from pathlib import Path
import json

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
OUT = Path(__file__).resolve().parent / "_full-sep-oct-mistake-audit.json"

REMOTE = r'''
import json, re, time, gzip
from collections import Counter, defaultdict
from pathlib import Path
from glob import glob

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

# Calendar
cal_days = {}
days = cal.get("days") or cal
if isinstance(days, list):
    for row in days:
        dk = str(row.get("date") or row.get("day") or "")[:10]
        if dk:
            cal_days[dk] = {
                "pnl": float(row.get("pnl") or row.get("profit") or 0),
                "n": row.get("n") or row.get("trades") or row.get("fills"),
            }
elif isinstance(days, dict):
    for dk, v in days.items():
        if isinstance(v, dict):
            cal_days[str(dk)[:10]] = {
                "pnl": float(v.get("pnl") or v.get("profit") or 0),
                "n": v.get("n") or v.get("trades") or v.get("fills"),
            }

# Screenshot / prior UI Sep baseline (authoritative when cache thin)
UI_SEP = {
    "2026-09-23": {"pnl": 5.51, "fills": 4},
    "2026-09-24": {"pnl": 61.81, "fills": 32},
    "2026-09-25": {"pnl": 76.01, "fills": 38},
    "2026-09-26": {"pnl": -11.49, "fills": 38},
    "2026-09-27": {"pnl": 0.0, "fills": 0},
    "2026-09-28": {"pnl": 147.79, "fills": 12},
    "2026-09-29": {"pnl": 0.0, "fills": 14},
}

# Deal closed PnL + side + quote
by_day = defaultdict(lambda: {
    "closes": 0, "opens": 0, "pnl": 0.0,
    "short_n": 0, "short_pnl": 0.0, "long_n": 0, "long_pnl": 0.0,
    "syms": Counter(), "big_losses": [],
})
for d in deals:
    t = ts(d)
    if not t:
        continue
    dk = day_key(t)
    if dk < "2026-09-23" or dk > "2026-10-10":
        continue
    slot = by_day[dk]
    if d.get("is_close"):
        slot["closes"] += 1
        p = pnl(d)
        slot["pnl"] += p
        side = str(d.get("position_side") or d.get("positionSide") or "").upper()
        if side == "SHORT":
            slot["short_n"] += 1
            slot["short_pnl"] += p
        elif side == "LONG":
            slot["long_n"] += 1
            slot["long_pnl"] += p
        slot["syms"][str(d.get("symbol") or "?")] += 1
        if p <= -10:
            slot["big_losses"].append({
                "t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t / 1000)),
                "sym": d.get("symbol"),
                "side": side,
                "pnl": round(p, 2),
                "quote": float(d.get("quote_qty") or 0) or None,
                "vol": d.get("volume") or d.get("qty"),
                "price": d.get("price"),
            })
    else:
        slot["opens"] += 1

# Episodes: same symbol+minute
eps = defaultdict(list)
for d in deals:
    if not d.get("is_close"):
        continue
    t = ts(d)
    dk = day_key(t)
    if dk < "2026-09-23" or dk > "2026-10-10":
        continue
    minute = time.strftime("%Y-%m-%d %H:%M", time.gmtime(t / 1000))
    eps[(dk, d.get("symbol"), minute)].append(d)

ep_by_day = defaultdict(lambda: {
    "MIX": [0, 0.0], "SHORT_ONLY": [0, 0.0], "LONG_ONLY": [0, 0.0], "OTHER": [0, 0.0],
})
worst_mix = []
for (dk, sym, minute), legs in eps.items():
    sides = {str(x.get("position_side") or "").upper() for x in legs}
    net = sum(pnl(x) for x in legs)
    has_s, has_l = "SHORT" in sides, "LONG" in sides
    kind = "MIX" if has_s and has_l else ("SHORT_ONLY" if has_s else ("LONG_ONLY" if has_l else "OTHER"))
    ep_by_day[dk][kind][0] += 1
    ep_by_day[dk][kind][1] += net
    if kind == "MIX" and net <= -8:
        worst_mix.append({
            "day": dk, "minute": minute, "sym": sym, "n": len(legs),
            "net": round(net, 2),
            "short": round(sum(pnl(x) for x in legs if str(x.get("position_side")).upper() == "SHORT"), 2),
            "long": round(sum(pnl(x) for x in legs if str(x.get("position_side")).upper() == "LONG"), 2),
        })

# Log markers by day across rotated logs
PATTERNS = {
    "SHORT_TP": re.compile(r"reason=SHORT_TP|closed .* reason=SHORT_TP"),
    "RESCUE": re.compile(r"reason=RESCUE|closed .* reason=RESCUE"),
    "INVALIDATION": re.compile(r"reason=INVALIDATION|closed .* reason=INVALIDATION"),
    "SMART_EXIT": re.compile(r"SMART_EXIT|reason=SMART_EXIT"),
    "SHORT_PULLBACK": re.compile(r"reason=SHORT_PULLBACK"),
    "LONG1_PULLBACK": re.compile(r"reason=LONG1_PULLBACK|LONG1_PULLBACK"),
    "LONG2_PULLBACK": re.compile(r"reason=LONG2_PULLBACK|LONG2_PULLBACK"),
    "SOLO_PAIR_FLATTEN": re.compile(r"PAIR_FLATTEN|paired hold blocks solo"),
    "SHORT_GONE": re.compile(r"SHORT_GONE"),
    "SAFE_MODE": re.compile(r"SAFE_MODE"),
    "rule_kernel": re.compile(r"rule_kernel|KERNEL_"),
    "ERR_4005": re.compile(r"-4005|code.?4005"),
    "ERR_4131": re.compile(r"-4131|code.?4131"),
    "ERR_2022": re.compile(r"-2022|code.?2022"),
    "ERR_429": re.compile(r"429|REST cooling"),
    "positions_unavailable": re.compile(r"positions unavailable|PositionsUnavailable|unavailable . not empty|unavailable — not empty"),
    "LEV_10": re.compile(r"exchange_leverage=10|target=10|leverage.?10"),
    "naked_10x": re.compile(r"naked.*10|force.*10x|LONG1_LEVERAGE.*naked", re.I),
    "INSTANT_FLATTEN": re.compile(r"instant.?flatten|max_wait_s=0|immediate flatten", re.I),
    "MANUAL": re.compile(r"manual=True|MANUAL_SHORT_FLATTEN|reason=MANUAL"),
    "OVERSIZE": re.compile(r"oversize|AAVE|clamp_manual|reject oversize", re.I),
    "defer_SHORT_TP": re.compile(r"defer SHORT_TP"),
    "LONG1_OPEN": re.compile(r"LONG1 open|opened LONG1|status=Long 1|LONG1_OPEN"),
    "LONG2_OPEN": re.compile(r"LONG2 open|opened LONG2|status=Long 2|LONG2_OPEN"),
    "SHORT_OPEN": re.compile(r"opened SHORT|SHORT open|status=Short[^ ],"),
}

def read_log(path):
    p = Path(path)
    try:
        if str(path).endswith(".gz"):
            return gzip.open(path, "rt", encoding="utf-8", errors="replace").read()
        return p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""

# Collect log text for Sep23–Oct10 (cap size)
files = sorted(glob("/var/log/bilshenz/app.log*")) + sorted(glob("/var/log/bilshenz/binance-api.log*"))
# Prefer uncompressed + recent gz
texts_by_day = defaultdict(list)
day_re = re.compile(r"(2026-09-2[3-9]|2026-09-30|2026-10-0[1-9]|2026-10-10)T")

marker_by_day = defaultdict(Counter)
# Stream line-by-line to avoid RAM blow
for fp in files:
    try:
        if fp.endswith(".gz"):
            fh = gzip.open(fp, "rt", encoding="utf-8", errors="replace")
        else:
            fh = open(fp, "r", encoding="utf-8", errors="replace")
    except Exception:
        continue
    with fh:
        for line in fh:
            m = day_re.search(line)
            if not m:
                continue
            dk = m.group(1)
            for name, pat in PATTERNS.items():
                if pat.search(line):
                    marker_by_day[dk][name] += 1

# Reason close lines with pnl context from scanner closed
close_reasons = defaultdict(Counter)
close_re = re.compile(
    r"(2026-09-2[3-9]|2026-09-30|2026-10-0[1-9]|2026-10-10)T[0-9:.]+Z? .*scanner closed ([A-Z0-9]+USDT) reason=([A-Z0-9_]+)"
)
for fp in ["/var/log/bilshenz/app.log"] + sorted(glob("/var/log/bilshenz/app.log.*.gz"))[:8]:
    try:
        if fp.endswith(".gz"):
            fh = gzip.open(fp, "rt", encoding="utf-8", errors="replace")
        else:
            fh = open(fp, "r", encoding="utf-8", errors="replace")
    except Exception:
        continue
    with fh:
        for line in fh:
            m = close_re.search(line)
            if m:
                close_reasons[m.group(1)][m.group(3)] += 1

# Era aggregates
ERAS = {
    "SEP_WIN_23_25": ["2026-09-23", "2026-09-24", "2026-09-25"],
    "SEP_26": ["2026-09-26"],
    "SEP_28": ["2026-09-28"],
    "DRIFT_29_30": ["2026-09-29", "2026-09-30"],
    "OCT_EARLY_1_4": ["2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04"],
    "OCT_CASCADE_5_8": ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"],
    "POST_FIX_9_10": ["2026-10-09", "2026-10-10"],
}

def era_deal(days_list):
    out = {"pnl": 0.0, "closes": 0, "short_pnl": 0.0, "long_pnl": 0.0,
           "mix_n": 0, "mix_pnl": 0.0, "naked_n": 0, "naked_pnl": 0.0}
    for dk in days_list:
        s = by_day.get(dk)
        if s:
            out["pnl"] += s["pnl"]
            out["closes"] += s["closes"]
            out["short_pnl"] += s["short_pnl"]
            out["long_pnl"] += s["long_pnl"]
        e = ep_by_day.get(dk)
        if e:
            out["mix_n"] += e["MIX"][0]
            out["mix_pnl"] += e["MIX"][1]
            out["naked_n"] += e["SHORT_ONLY"][0]
            out["naked_pnl"] += e["SHORT_ONLY"][1]
    for k in list(out):
        if isinstance(out[k], float):
            out[k] = round(out[k], 2)
    return out

def era_markers(days_list):
    c = Counter()
    for dk in days_list:
        c.update(marker_by_day.get(dk, {}))
    return dict(c.most_common(40))

era_out = {}
for name, dlist in ERAS.items():
    ui_pnl = sum(float((UI_SEP.get(d) or cal_days.get(d) or {}).get("pnl") or 0) for d in dlist)
    # Prefer calendar for Oct
    cal_pnl = 0.0
    for d in dlist:
        if d in cal_days:
            cal_pnl += cal_days[d]["pnl"]
        elif d in UI_SEP:
            cal_pnl += UI_SEP[d]["pnl"]
    era_out[name] = {
        "days": dlist,
        "ui_or_cal_pnl": round(cal_pnl, 2),
        "deals": era_deal(dlist),
        "markers": era_markers(dlist),
        "close_reasons": dict(sum((close_reasons.get(d, Counter()) for d in dlist), Counter()).most_common(20)),
    }

# Size sanity Oct vs Sep
size_breaks = []
for d in deals:
    if not d.get("is_close"):
        continue
    dk = day_key(ts(d))
    if dk < "2026-09-23":
        continue
    q = float(d.get("quote_qty") or 0)
    side = str(d.get("position_side") or "").upper()
    if side == "SHORT" and q > 320:
        size_breaks.append({"day": dk, "sym": d.get("symbol"), "side": side, "q": round(q, 2), "pnl": round(pnl(d), 2)})
    if side == "LONG" and q > 900:
        size_breaks.append({"day": dk, "sym": d.get("symbol"), "side": side, "q": round(q, 2), "pnl": round(pnl(d), 2)})

out = {
    "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    "ui_sep": UI_SEP,
    "calendar": {k: cal_days[k] for k in sorted(cal_days) if k >= "2026-09-23"},
    "deal_days": {
        dk: {
            "closes": v["closes"], "opens": v["opens"], "pnl": round(v["pnl"], 2),
            "short_n": v["short_n"], "short_pnl": round(v["short_pnl"], 2),
            "long_n": v["long_n"], "long_pnl": round(v["long_pnl"], 2),
            "top_syms": v["syms"].most_common(5),
            "big_losses": sorted(v["big_losses"], key=lambda x: x["pnl"])[:8],
        }
        for dk, v in sorted(by_day.items())
    },
    "episodes_by_day": {
        dk: {k: {"n": v[0], "pnl": round(v[1], 2)} for k, v in kinds.items()}
        for dk, kinds in sorted(ep_by_day.items())
    },
    "worst_mix": sorted(worst_mix, key=lambda x: x["net"])[:25],
    "eras": era_out,
    "size_breaks_n": len(size_breaks),
    "size_breaks_sample": size_breaks[:15],
    "close_reasons_by_day": {dk: dict(c) for dk, c in sorted(close_reasons.items())},
}
print(json.dumps(out))
'''


def main() -> None:
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", key_filename=str(KEY), timeout=30)
    sftp = c.open_sftp()
    with sftp.file("/tmp/_full-sep-oct-mistake-audit.py", "w") as f:
        f.write(REMOTE)
    sftp.close()
    _, o, e = c.exec_command(
        "/opt/bilshenz/binance_trading_system/python/.venv/bin/python /tmp/_full-sep-oct-mistake-audit.py",
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
    # Compact console summary
    print("=== ERAS ===")
    for name, e in data["eras"].items():
        d = e["deals"]
        print(
            f"{name}: ui/cal={e['ui_or_cal_pnl']} deal_pnl={d['pnl']} "
            f"mix={d['mix_n']}/{d['mix_pnl']} naked={d['naked_n']}/{d['naked_pnl']}"
        )
        m = e["markers"]
        keys = [
            "SAFE_MODE", "rule_kernel", "ERR_4005", "ERR_4131", "ERR_429",
            "SHORT_GONE", "INSTANT_FLATTEN", "LONG1_PULLBACK", "RESCUE",
            "SHORT_TP", "INVALIDATION", "positions_unavailable", "defer_SHORT_TP",
        ]
        hits = {k: m.get(k, 0) for k in keys if m.get(k)}
        print("  markers", hits)
        print("  close_reasons", e["close_reasons"])


if __name__ == "__main__":
    main()
