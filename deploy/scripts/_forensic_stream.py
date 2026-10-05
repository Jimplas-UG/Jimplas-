#!/usr/bin/env python3
"""Streaming forensic — no full-log RAM load. Run on VPS."""
from __future__ import annotations

import gzip
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

LOG_DIR = Path("/var/log/bilshenz")
CACHE = Path("/var/lib/bilshenz/trade-history-cache.json")
RISK = Path("/var/lib/bilshenz/scanner-risk.json")

DAYS = {
    "2026-09-23",
    "2026-09-24",
    "2026-09-25",
    "2026-09-26",
    "2026-09-27",
    "2026-09-28",
    "2026-09-29",
    "2026-09-30",
    "2026-10-01",
}
BASE = {"2026-09-23", "2026-09-24", "2026-09-25"}
RECENT = {"2026-09-29", "2026-09-30", "2026-10-01"}

close_re = re.compile(r"reason=([A-Z0-9_]+)")
short_ok_re = re.compile(r"scanner SHORT (\w+) qty=([0-9.]+) @ ([0-9.]+)")
smart_re = re.compile(
    r"SMART_EXIT.*?pnl=([-0-9.]+) target=([-0-9.]+)(?:.*?hedges=(\w+).*?short_underwater=(\w+))?"
)
login_re = re.compile(r"mode=(\w+).*auto=(\w+)")


def open_log(path: Path):
    if str(path).endswith(".gz"):
        return gzip.open(path, "rt", errors="replace")
    return path.open("rt", errors="replace")


def main() -> int:
    print("RISK", RISK.read_text().strip() if RISK.exists() else "missing", flush=True)
    sys.path.insert(0, "/opt/bilshenz/binance_trading_system/python")
    from frozen_strategy import assert_frozen_contract
    import momentum_scanner as ms

    snap = assert_frozen_contract()
    print("CONTRACT", snap["strategy_id"], snap.get("ops"), flush=True)
    print("SMART_EXIT", ms.SMART_EXIT_NET_PCT, flush=True)

    summary = {d: Counter() for d in DAYS}
    smarts = defaultdict(list)
    shorts = defaultdict(list)
    timeline = []
    samples = {"base": [], "recent": []}

    files = sorted(LOG_DIR.glob("binance-api.log*"), key=lambda p: p.stat().st_mtime)
    for path in files:
        print("SCAN", path.name, path.stat().st_size, flush=True)
        try:
            f = open_log(path)
        except Exception as e:
            print("OPEN_FAIL", path, e, flush=True)
            continue
        with f:
            for ln in f:
                day = ln[:10]
                if day not in DAYS:
                    # still catch timeline around flips outside DAYS? skip
                    continue
                c = summary[day]

                if "login success" in ln:
                    c["LOGIN_OK"] += 1
                    m = login_re.search(ln)
                    mode = m.group(1) if m else "?"
                    if mode == "live":
                        c["LOGIN_MAINNET"] += 1
                    if mode == "testnet":
                        c["LOGIN_TESTNET"] += 1
                    if len(timeline) < 200:
                        timeline.append((ln[:19], "LOGIN_OK", m.group(0) if m else mode))
                elif "login attempt" in ln and len(timeline) < 200:
                    m = re.search(r"testnet=(\w+)", ln)
                    timeline.append((ln[:19], "LOGIN_TRY", f"testnet={m.group(1) if m else '?'}"))
                elif "restarting market streams" in ln and len(timeline) < 200:
                    timeline.append((ln[:19], "STREAM_RESTART", ""))
                elif ("FORCE_MAIN" in ln or "force_mainnet" in ln.lower()) and len(timeline) < 200:
                    timeline.append((ln[:19], "FORCE_MAIN", ln[-80:]))

                if "scanner closed" in ln:
                    m = close_re.search(ln)
                    if m:
                        c[m.group(1)] += 1
                if "reason=SMART_EXIT" in ln:
                    c["SMART_EXIT_CLOSE"] += 1
                if "SMART_EXIT" in ln and "pnl=" in ln:
                    c["SMART_EXIT_DECIDE"] += 1
                    m = smart_re.search(ln)
                    if m:
                        smarts[day].append(
                            (float(m.group(1)), float(m.group(2)), m.group(3), m.group(4))
                        )
                if "scanner SHORT " in ln and "qty=" in ln and "failed" not in ln:
                    m = short_ok_re.search(ln)
                    if m:
                        qty, px = float(m.group(2)), float(m.group(3))
                        shorts[day].append((m.group(1), qty * px))
                        c["SHORT_OPEN"] += 1
                if "scanner SHORT failed" in ln:
                    c["SHORT_FAIL"] += 1
                if "EXEC_FAIL" in ln:
                    c["EXEC_FAIL"] += 1
                    if "cooling" in ln or "418" in ln:
                        c["EXEC_FAIL_COOL"] += 1
                if "MANUAL_" in ln or "manual close" in ln.lower():
                    c["MANUAL"] += 1
                if "scanner LONG1 " in ln and "qty=" in ln and "failed" not in ln and "blocked" not in ln:
                    c["LONG1_OPEN"] += 1
                if "scanner LONG2 " in ln and "qty=" in ln and "failed" not in ln and "blocked" not in ln:
                    c["LONG2_OPEN"] += 1
                if "clearing REST cool" in ln or "clearing residual cool" in ln:
                    c["COOL_CLEAR"] += 1
                if "immediate flatten" in ln:
                    c["INSTANT_FLATTEN"] += 1
                if "paired hold" in ln.lower() or "PAIRED_HOLD" in ln:
                    c["PAIRED_HOLD"] += 1

                interesting = any(
                    x in ln
                    for x in (
                        "scanner closed",
                        "SMART_EXIT",
                        "MANUAL_",
                        "INVALIDATION",
                        "RESCUE",
                        "PULLBACK",
                        "SHORT_TP",
                        "immediate flatten",
                        "EXEC_FAIL",
                        "login success",
                    )
                )
                if interesting and "positions: Binance REST" not in ln and "margin cache" not in ln:
                    bucket = None
                    if day in BASE and len(samples["base"]) < 60:
                        bucket = "base"
                    elif day in RECENT and len(samples["recent"]) < 120:
                        bucket = "recent"
                    if bucket:
                        samples[bucket].append(ln[:240])

    print("\n=== TIMELINE ===", flush=True)
    for t in timeline:
        print(t[0], t[1], t[2], flush=True)

    print("\n=== PER-DAY ===", flush=True)
    for day in sorted(DAYS):
        c = summary[day]
        ns = [n for _, n in shorts[day]]
        avg = round(sum(ns) / len(ns), 2) if ns else None
        print(day, "shorts", len(ns), "avg_notional", avg, flush=True)
        print(" ", {k: v for k, v in sorted(c.items()) if v}, flush=True)
        sm = smarts[day]
        if sm:
            avg_p = round(sum(p for p, *_ in sm) / len(sm), 4)
            print("  smart_avg_pnl", avg_p, "n", len(sm), "samples", sm[:5], flush=True)

    print("\n=== MIX base vs recent ===", flush=True)
    bm, rm = Counter(), Counter()
    for d in BASE:
        bm.update(summary[d])
    for d in RECENT:
        rm.update(summary[d])
    print(f"{'metric':32} {'base_23-25':>12} {'recent_29-01':>12}", flush=True)
    for k in sorted(set(bm) | set(rm)):
        print(f"{k:32} {bm.get(k, 0):12} {rm.get(k, 0):12}", flush=True)

    print("\n=== TRADE CACHE ===", flush=True)
    by_day = defaultdict(lambda: {"pnl": 0.0, "n": 0, "w": 0, "l": 0, "gw": 0.0, "gl": 0.0})
    by_sym_day = defaultdict(lambda: defaultdict(float))
    worst = []
    if CACHE.exists():
        rows = json.loads(CACHE.read_text()).get("deals") or []
        for r in rows:
            if not isinstance(r, dict):
                continue
            try:
                pnl = float(r.get("profit", r.get("realized_pnl", r.get("realizedPnl"))))
            except Exception:
                continue
            try:
                t = int(r.get("time") or 0)
            except Exception:
                continue
            if t and t < 1e12:
                t *= 1000
            if not t:
                continue
            day = datetime.fromtimestamp(t / 1000, timezone.utc).strftime("%Y-%m-%d")
            if day < "2026-09-23":
                continue
            is_close = bool(r.get("is_close") or r.get("isClose"))
            if not is_close and abs(pnl) < 1e-12:
                continue
            b = by_day[day]
            b["pnl"] += pnl
            b["n"] += 1
            if pnl > 0:
                b["w"] += 1
                b["gw"] += pnl
            elif pnl < 0:
                b["l"] += 1
                b["gl"] += pnl
            by_sym_day[day][str(r.get("symbol"))] += pnl
            worst.append((pnl, day, r.get("symbol"), r.get("type"), r.get("position_side"), t, is_close))
        for day in sorted(DAYS):
            b = by_day[day]
            print(
                day,
                "n",
                b["n"],
                "pnl",
                round(b["pnl"], 2),
                "W/L",
                f"{b['w']}/{b['l']}",
                "gw",
                round(b["gw"], 2),
                "gl",
                round(b["gl"], 2),
                flush=True,
            )
            if by_sym_day[day]:
                print("  worst_syms", [(s, round(v, 2)) for s, v in sorted(by_sym_day[day].items(), key=lambda kv: kv[1])[:6]], flush=True)
        print("WORST20", flush=True)
        for pnl, day, sym, typ, ps, t, ic in sorted(worst, key=lambda x: x[0])[:20]:
            ts = datetime.fromtimestamp(t / 1000, timezone.utc).isoformat()
            print(f"  {ts} {sym} {typ}/{ps} {pnl:.2f} close={ic}", flush=True)

        base_pnl = sum(by_day[d]["pnl"] for d in BASE)
        recent_pnl = sum(by_day[d]["pnl"] for d in RECENT)
        print("SUM_BASE_23-25", round(base_pnl, 2), flush=True)
        print("SUM_RECENT_29-01", round(recent_pnl, 2), flush=True)

    print("\n=== SAMPLE BASE CLOSES ===", flush=True)
    for ln in samples["base"]:
        print(ln, flush=True)
    print("\n=== SAMPLE RECENT CLOSES ===", flush=True)
    for ln in samples["recent"]:
        print(ln, flush=True)

    print("DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
