#!/usr/bin/env python3
"""Long-run soak on one bot: rotating synthetic regimes, random faults and daily restarts.

  python sim/soak.py --code <dir> --days 30 --out soak.json

Prints one row per virtual day, so slow growth in memory or errors is visible.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import random
import sys
import time
from pathlib import Path

_process_time = time.process_time  # Real CPU time, untouched by the virtual clock.
sys.path.insert(0, str(Path(__file__).resolve().parent))


def rss_mb() -> float:
    try:
        import psutil

        return psutil.Process().memory_info().rss / 1048576
    except ImportError:
        pass
    if sys.platform == "win32":
        class PMC(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("pf", ctypes.c_ulong), ("peak", ctypes.c_size_t),
                        ("ws", ctypes.c_size_t)] + [(f"x{i}", ctypes.c_size_t) for i in range(6)]

        pmc = PMC()
        pmc.cb = ctypes.sizeof(PMC)
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(k.GetCurrentProcess()), ctypes.byref(pmc), pmc.cb)
        return pmc.ws / 1048576
    return 0.0


def continue_prices(ticks: list, last_px: dict) -> list:
    """Each regime starts at its base price. Carry price over, or the seam is a fake 40% gap."""
    scale: dict = {}
    out = []
    for t, sym, px in ticks:
        k = scale.setdefault(sym, last_px.get(sym, px) / px)
        out.append((t, sym, px * k))
        last_px[sym] = px * k
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--code", required=True)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    import scenarios
    from fake_exchange import Fault
    from harness import START_EPOCH, Sim

    rng = random.Random(a.seed)
    sim = Sim(a.code, scenarios.SYMS, testnet=False)
    sim.boot()
    names = list(scenarios.REGIMES)
    fault_names = [k for k in scenarios.ORDER_FAULTS if not k.startswith("http418")]
    days = []
    recovery_s = []
    last_px: dict = {}
    t0 = START_EPOCH
    cpu0 = _process_time()
    for day in range(a.days):
        for half in range(2):
            builder = scenarios.REGIMES[names[(day * 2 + half) % len(names)]]
            regime, ex_kw, hooks = builder(rng.randrange(1 << 30))
            regime.dt = 5.0
            base = dict(depth_usd=0.0, spread_bps=2.0, slip_bps=0.0, funding_rate=0.0001)
            base.update(ex_kw)
            for k, v in base.items():
                setattr(sim.ex, k, v)
            sim.ex.faults = [
                Fault(leg=rng.choice(list(scenarios.LEGS.values())), count=1, **scenarios.ORDER_FAULTS[rng.choice(fault_names)])
                for _ in range(6)
            ]
            offset = t0 - START_EPOCH
            shifted = [(h + offset, fn) for h, fn in hooks]
            if half == 0:
                at = rng.uniform(2, 10) * 3600 + offset
                down = rng.uniform(10, 120)

                def crash(x: Sim) -> None:
                    x.crash()

                def boot(x: Sim) -> None:
                    x.boot()
                    recovery_s.append(x.boot_recovery[-1]["virtual_s"])

                shifted += [(at, crash), (at + down, boot)]
            sim.run(continue_prices(regime.ticks(t0), last_px), hooks=shifted)
            t0 += regime.hours * 3600
        s = sim.summary()
        row = {
            "day": day + 1, "rss_mb": round(rss_mb(), 1), "cpu_s": round(_process_time() - cpu0, 1),
            "ticks": s["ticks"], "api_calls": s["api_calls"], "trades": s["signals"],
            "faults": s["faults_fired"], "rejects": s["rejects"], "dup_ids": len(s["dup_client_ids"]),
            "stacked": s["stacked_fills"], "exceptions": s["unhandled_tick_exceptions"],
            "worst_unmanaged_s": s["worst_unmanaged_s"], "worst_phantom_s": s["worst_phantom_s"],
            "worst_mismatch_s": s["worst_mismatch_s"], "naked_long_s": s["naked_long_s"],
            "multi_symbol_s": s["multi_symbol_s"], "liquidations": s["liquidations"], "net": s["net"],
            "max_dd": s["max_drawdown"], "boots": sim.boots,
            "breaker_trips": sim.sc._engine.breaker.trips if sim.sc and hasattr(sim.sc._engine, "breaker") else None,
        }
        days.append(row)
        print(json.dumps(row), flush=True)
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump({"days": days, "recovery_virtual_s": recovery_s, "final": s}, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main())
