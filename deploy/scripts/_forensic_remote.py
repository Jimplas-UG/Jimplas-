#!/usr/bin/env python3
"""Forensic analyzer — run ON the VPS. Read-only."""
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
ENV = Path("/etc/bilshenz.env")
RISK = Path("/var/lib/bilshenz/scanner-risk.json")

DAYS = [
    "2026-09-23",
    "2026-09-24",
    "2026-09-25",
    "2026-09-26",
    "2026-09-27",
    "2026-09-28",
    "2026-09-29",
    "2026-09-30",
    "2026-10-01",
]


def load_all_logs() -> str:
    parts: list[str] = []
    files = sorted(LOG_DIR.glob("binance-api.log*"), key=lambda p: p.stat().st_mtime)
    for name in files:
        try:
            if str(name).endswith(".gz"):
                with gzip.open(name, "rt", errors="replace") as f:
                    parts.append(f.read())
            else:
                parts.append(name.read_text(errors="replace"))
            print("LOG_FILE", name.name, "bytes", name.stat().st_size, flush=True)
        except Exception as e:
            print("LOG_READ_FAIL", name, e, flush=True)
    return "\n".join(parts)


def main() -> int:
    print("=== ENV / RISK ===", flush=True)
    env: dict[str, str] = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k] = v.strip().strip('"').strip("'")
    for k in (
        "BINANCE_TESTNET",
        "BINANCE_FORCE_MAINNET",
        "BINANCE_PAPER",
        "SCANNER_EXEC",
        "FORWARD_DRY_RUN",
        "SCANNER_PARTITION_USD",
        "SCANNER_SMART_EXIT_PCT",
    ):
        if k in env:
            print(f"  {k}={env[k]}", flush=True)
    if RISK.exists():
        print("RISK", RISK.read_text().strip()[:400], flush=True)

    sys.path.insert(0, "/opt/bilshenz/binance_trading_system/python")
    from frozen_strategy import assert_frozen_contract
    import momentum_scanner as ms
    import inspect
    import binance_connector as bc

    snap = assert_frozen_contract()
    print("CONTRACT", snap["strategy_id"], "ops", snap.get("ops"), flush=True)
    print("LIVE SMART_EXIT", ms.SMART_EXIT_NET_PCT, flush=True)
    cool_src = inspect.getsource(bc.BinanceConnector._wait_or_clear_cool_for_close)
    print("CLOSE_COOL_12", "max_wait_s: float = 12.0" in cool_src, flush=True)
    print("SHORT_OK_GUARD", "short_ok_for_smart" in Path(ms.__file__).read_text(encoding="utf-8"), flush=True)

    print("\n=== LOAD LOGS ===", flush=True)
    text = load_all_logs()
    print("LOG_CHARS", len(text), flush=True)
    all_lines = text.splitlines()

    print("\n=== MODE / PARTITION / LOGIN TIMELINE ===", flush=True)
    timeline = []
    for ln in all_lines:
        day = ln[:10]
        if not (day.startswith("2026-09") or day.startswith("2026-10")):
            continue
        if "login success" in ln:
            m = re.search(r"mode=(\w+).*auto=(\w+)", ln)
            timeline.append((ln[:19], "LOGIN_OK", m.group(0) if m else ln[-90:]))
        elif "login attempt" in ln and "testnet=" in ln:
            m = re.search(r"key=([^…]+).*testnet=(\w+)", ln)
            timeline.append((ln[:19], "LOGIN_TRY", m.group(0) if m else ln[-80:]))
        elif "restarting market streams" in ln:
            timeline.append((ln[:19], "STREAM_RESTART", ln[-90:]))
        elif "FORCE_MAIN" in ln or "force_mainnet" in ln.lower():
            timeline.append((ln[:19], "FORCE_MAIN", ln[-100:]))
        elif "partition_usd" in ln and ("risk" in ln.lower() or "set" in ln.lower() or "update" in ln.lower()):
            timeline.append((ln[:19], "PARTITION", ln[-120:]))
        elif re.search(r"partition[=:].*?\d+", ln, re.I) and "scanner SHORT" in ln:
            pass
        elif "BINANCE_TESTNET" in ln or "switched to" in ln.lower():
            timeline.append((ln[:19], "MODE_NOTE", ln[-120:]))
    for row in timeline[:150]:
        print(row[0], row[1], row[2], flush=True)
    print("TIMELINE_N", len(timeline), flush=True)

    print("\n=== PER-DAY ACTIVITY ===", flush=True)
    close_re = re.compile(r"reason=([A-Z0-9_]+)")
    short_ok_re = re.compile(r"scanner SHORT (\w+) qty=([0-9.]+) @ ([0-9.]+)")
    smart_re = re.compile(
        r"SMART_EXIT.*?pnl=([-0-9.]+) target=([-0-9.]+)(?:.*?hedges=(\w+).*?short_underwater=(\w+))?"
    )
    summary: dict[str, dict] = {}

    # index lines by day once
    by_day_lines: dict[str, list[str]] = defaultdict(list)
    for ln in all_lines:
        d = ln[:10]
        if d in DAYS:
            by_day_lines[d].append(ln)

    for day in DAYS:
        lines = by_day_lines[day]
        c: Counter = Counter()
        smart = []
        shorts = []
        for ln in lines:
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
                    smart.append(
                        (
                            float(m.group(1)),
                            float(m.group(2)),
                            m.group(3),
                            m.group(4),
                        )
                    )
            if "scanner SHORT " in ln and "qty=" in ln and "failed" not in ln:
                m = short_ok_re.search(ln)
                if m:
                    qty, px = float(m.group(2)), float(m.group(3))
                    shorts.append((m.group(1), qty * px))
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
            if "login success" in ln:
                c["LOGIN_OK"] += 1
                if "mode=live" in ln:
                    c["LOGIN_MAINNET"] += 1
                if "mode=testnet" in ln:
                    c["LOGIN_TESTNET"] += 1
            if "paired hold" in ln.lower() or "PAIRED_HOLD" in ln:
                c["PAIRED_HOLD"] += 1
            if "orphan" in ln.lower():
                c["ORPHAN"] += 1
        notionals = [n for _, n in shorts]
        summary[day] = {
            "lines": len(lines),
            "counts": dict(c),
            "short_n": len(shorts),
            "avg_short_notional": round(sum(notionals) / len(notionals), 2) if notionals else None,
            "smart": smart[:8],
            "smart_avg": round(sum(p for p, *_ in smart) / len(smart), 4) if smart else None,
        }
        print(
            day,
            "lines",
            len(lines),
            "shorts",
            len(shorts),
            "avg_notional",
            summary[day]["avg_short_notional"],
            flush=True,
        )
        print(" ", {k: v for k, v in sorted(c.items()) if v}, flush=True)
        if smart:
            print("  smart_avg", summary[day]["smart_avg"], "samples", smart[:5], flush=True)

    print("\n=== TRADE CACHE PnL ===", flush=True)
    by_day = defaultdict(lambda: {"pnl": 0.0, "n": 0, "wins": 0, "losses": 0, "gw": 0.0, "gl": 0.0})
    by_day_sym = defaultdict(lambda: defaultdict(float))
    worst = []
    reasonish = []
    if CACHE.exists():
        d = json.loads(CACHE.read_text())
        rows = d.get("deals") or []
        for r in rows:
            if not isinstance(r, dict):
                continue
            pnl = r.get("profit", r.get("realized_pnl", r.get("realizedPnl")))
            try:
                pnl = float(pnl)
            except Exception:
                continue
            t = r.get("time") or 0
            try:
                t = int(t)
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
                b["wins"] += 1
                b["gw"] += pnl
            elif pnl < 0:
                b["losses"] += 1
                b["gl"] += pnl
            by_day_sym[day][str(r.get("symbol"))] += pnl
            worst.append((pnl, day, r.get("symbol"), r.get("type"), r.get("position_side"), t, is_close, r.get("comment") or r.get("reason")))
        for day in DAYS:
            b = by_day[day]
            print(
                day,
                "n",
                b["n"],
                "pnl",
                round(b["pnl"], 2),
                "W/L",
                f"{b['wins']}/{b['losses']}",
                "grossW",
                round(b["gw"], 2),
                "grossL",
                round(b["gl"], 2),
                flush=True,
            )
            if by_day_sym[day]:
                top = sorted(by_day_sym[day].items(), key=lambda kv: kv[1])[:6]
                print("  worst_syms", [(s, round(v, 2)) for s, v in top], flush=True)
        print("WORST20 since 09-23", flush=True)
        for row in sorted(worst, key=lambda x: x[0])[:20]:
            pnl, day, sym, typ, ps, t, ic, reason = row
            ts = datetime.fromtimestamp(t / 1000, timezone.utc).isoformat()
            print(f"  {ts} {sym} {typ}/{ps} pnl={pnl:.2f} close={ic} reason={reason}", flush=True)
    else:
        print("NO_CACHE", flush=True)

    print("\n=== BASELINE vs RECENT CLOSE MIX ===", flush=True)
    base_days = ["2026-09-23", "2026-09-24", "2026-09-25"]
    recent_days = ["2026-09-29", "2026-09-30", "2026-10-01"]

    def mix(days):
        tot: Counter = Counter()
        for d in days:
            tot.update(summary[d]["counts"])
        return tot

    bm, rm = mix(base_days), mix(recent_days)
    print(f"{'metric':32} {'base_23-25':>12} {'recent_29-01':>12}", flush=True)
    for k in sorted(set(bm) | set(rm)):
        print(f"{k:32} {bm.get(k, 0):12} {rm.get(k, 0):12}", flush=True)

    print("\n=== INSTANT-CLOSE / COOL MARKERS ===", flush=True)
    for needle in (
        "immediate flatten",
        "clearing REST cool",
        "clearing residual cool",
        "brief wait",
        "waiting",
    ):
        n = sum(1 for ln in all_lines if needle in ln and (ln.startswith("2026-09-2") or ln.startswith("2026-09-3") or ln.startswith("2026-10-01")))
        print(needle, n, flush=True)

    # Detailed SMART_EXIT / MANUAL / INVALIDATION lines on loss days
    print("\n=== KEY CLOSE LINES Sep29-Oct01 ===", flush=True)
    for day in recent_days:
        print("---", day, flush=True)
        n = 0
        for ln in by_day_lines[day]:
            if any(
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
            ):
                if "positions: Binance REST" in ln or "margin cache" in ln:
                    continue
                print(ln[:260], flush=True)
                n += 1
                if n >= 80:
                    print("...truncated", flush=True)
                    break

    print("\n=== KEY CLOSE LINES Sep23-25 (sample) ===", flush=True)
    for day in base_days:
        print("---", day, flush=True)
        n = 0
        for ln in by_day_lines[day]:
            if any(x in ln for x in ("scanner closed", "SMART_EXIT", "MANUAL_", "SHORT_TP", "INVALIDATION", "RESCUE", "PULLBACK")):
                if "positions: Binance REST" in ln:
                    continue
                print(ln[:260], flush=True)
                n += 1
                if n >= 40:
                    print("...truncated", flush=True)
                    break

    print("\nDONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
