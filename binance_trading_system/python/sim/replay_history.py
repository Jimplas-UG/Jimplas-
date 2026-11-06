#!/usr/bin/env python3
"""Replay recorded 1m klines through the real scanner, connector and engine.

  python sim/replay_history.py --code <dir> --data <kl dir> --start 2026-09-23 --end 2026-09-26 \
      --slip-bps 5 --out result.json

Bars become ticks in time order: open, the near extreme, the far extreme, close. Which extreme
came first inside a bar is not recorded, so a red bar goes high first and a green bar low first.
Large moves are split into small steps, so a threshold fills near its level rather than at the
far end of the bar. Decisions only ever see ticks already played.

Coins are fed only around real moves (15m gain of 4% or more, with 25 bars before and 40 after)
plus whichever coin holds a position. Everything else cannot qualify at the 5% gate.

Assumptions: taker 0.04%, 2 bps spread, slippage from --slip-bps, funding 0.01% per 8h.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))


def epoch(day: str) -> int:
    return int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp())


def load(data_dir: str, start: int, end: int) -> dict[str, dict[str, np.ndarray]]:
    t0, t1 = (start - 86400) * 1000, end * 1000
    out = {}
    for f in sorted(glob.glob(os.path.join(data_dir, "*.npz"))):
        z = np.load(f)
        t = z["t"]
        m = (t >= t0) & (t < t1)
        if m.sum() < 60:
            continue
        out[os.path.basename(f)[:-4]] = {k: z[k][m] for k in ("t", "o", "h", "l", "c", "qv")}
    return out


def active_minutes(rows: dict[str, np.ndarray], start: int) -> tuple[np.ndarray, np.ndarray]:
    c, h = rows["c"], rows["h"]
    n = len(c)
    gain = np.zeros(n)
    gain[15:] = (h[15:] / c[:-15] - 1.0) * 100
    hot = gain >= 4.0
    mask = np.zeros(n + 1, dtype=np.int32)
    for i in np.nonzero(hot)[0]:
        mask[max(0, i - 25)] += 1
        mask[min(n, i + 41)] -= 1
    active = np.cumsum(mask)[:n] > 0
    vol = np.convolve(rows["qv"], np.ones(1440), "full")[:n]
    return active, vol


def bar_ticks(o: float, h: float, low: float, c: float) -> list[float]:
    pts = [o, low, h, c] if c >= o else [o, h, low, c]
    out = [pts[0]]
    for a, b in zip(pts, pts[1:]):
        if a <= 0:
            continue
        steps = min(24, max(1, int(abs(b / a - 1) / 0.0015)))
        out += [a + (b - a) * (i + 1) / steps for i in range(steps)]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--data", required=True)
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--slip-bps", type=float, default=5.0)
    ap.add_argument("--all-coins", action="store_true")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    start, end = epoch(a.start), epoch(a.end)
    data = load(a.data, start, end)
    syms = sorted(data)
    idx = {}
    by_minute: dict[int, list[tuple[str, int]]] = {}
    vols = {}
    for s in syms:
        act, vol = active_minutes(data[s], start)
        vols[s] = vol
        ts = data[s]["t"] // 1000
        idx[s] = {int(t): i for i, t in enumerate(ts)}
        for i in np.nonzero(act | a.all_coins)[0] if not a.all_coins else range(len(ts)):
            t = int(ts[i])
            if start - 1800 <= t < end:
                by_minute.setdefault(t, []).append((s, int(i)))

    import harness
    from harness import Sim

    harness.START_EPOCH = float(start - 1800)
    sim = Sim(a.code, syms, testnet=False, slip_bps=a.slip_bps, spread_bps=2.0, wallet=5000.0)
    sim.clock.true = float(start - 1800)
    sim.ex.t0 = sim.clock.true
    sim.ex._last_funding_slot = int(sim.clock.true // 28800)
    for s in syms:
        px = float(data[s]["o"][0])
        sim.ex.px[s] = px
        # Typical USD-M lot steps: whole units on cheap coins, finer as price rises.
        sim.ex.step_of[s] = 1.0 if px < 0.5 else 0.1 if px < 10 else 0.01 if px < 500 else 0.001
        sim.ex.tick_of[s] = 10.0 ** np.floor(np.log10(max(px, 1e-9) / 20000.0))
    sim.boot()

    daily: dict[str, float] = {}
    day_key = ""
    total_ticks = 0
    for minute in sorted(by_minute):
        rows = list(by_minute[minute])
        held = {k[0] for k in sim.ex.pos}
        have = {r[0] for r in rows}
        for s in held - have:
            i = idx[s].get(minute)
            if i is not None:
                rows.append((s, i))
        key = dt.datetime.fromtimestamp(minute, dt.timezone.utc).strftime("%Y-%m-%d")
        if key != day_key:
            day_key = key
        series = []
        for s, i in rows:
            d = data[s]
            pts = bar_ticks(float(d["o"][i]), float(d["h"][i]), float(d["l"][i]), float(d["c"][i]))
            n = len(pts)
            series += [(minute + 59.0 * j / max(1, n - 1), s, p, float(vols[s][i])) for j, p in enumerate(pts)]
        series.sort(key=lambda r: r[0])
        for t, s, p, v in series:
            sim.quote_vol = v
            sim.tick(s, p, t)
            total_ticks += 1
        daily[key] = sim.ex.equity() - sim.ex.start_wallet

    out = sim.summary()
    out.update(
        {
            "start": a.start, "end": a.end, "slip_bps": a.slip_bps, "coins": len(syms),
            "ticks_fed": total_ticks, "daily_cum": daily,
        }
    )
    with open(a.out, "w", encoding="utf-8") as fh:
        json.dump({"summary": out, "trace": sim.trace(), "rejects": sim.ex.rejects[:400], "fills": sim.ex.fills[:400], "log": [r[1:] for r in sim.log.rows[:300]]}, fh)
    print(json.dumps({k: out[k] for k in ("start", "end", "slip_bps", "signals", "opens", "net", "realized_pnl", "fees", "funding", "slippage", "max_drawdown", "peak_notional", "peak_margin", "liquidations", "unhandled_tick_exceptions", "ticks_fed", "exit_reasons")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
