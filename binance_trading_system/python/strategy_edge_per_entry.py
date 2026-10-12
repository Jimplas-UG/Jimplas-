"""Per-entry expectancy (no one-at-a-time blocking) — stable edge estimate per variant/window."""

from __future__ import annotations

import pickle
import statistics
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import run_short_first_backtest as bt  # noqa: E402
import strategy_variant_research as svr  # noqa: E402

TAG = sys.argv[1] if len(sys.argv) > 1 else ""


def _load() -> dict[str, list[dict]]:
    out = {}
    for p in sorted(svr.CACHE.glob(f"*_1m_60d_{TAG}*.pkl")):
        out[p.name.split("_1m_")[0]] = pickle.loads(p.read_bytes())
    return out


def main() -> None:
    bars = _load()
    last = max(b[-1]["t"] for b in bars.values())
    first = min(b[0]["t"] for b in bars.values())
    cut = last - 30 * 86_400_000
    variants = {
        "live_frozen": {},
        "frozen_hold24h": {"HEDGED_MAX_HOLD_MIN": 1440},
    }
    for r in (1.5, 3.0, 4.0, 5.0, 6.0):
        variants[f"r{r:g}_hold24h"] = {"RETRACE_ENTRY_PCT": r, "HEDGED_MAX_HOLD_MIN": 1440}
    variants["naked_inv6.5"] = {"LONG1_ADVERSE_PCT": svr.OFF, "LONG2_ADVERSE_PCT": svr.OFF}
    for name, ov in variants.items():
        svr._apply(ov)
        row = [f"{name:16s}"]
        for label, t0, t1 in (("TRAIN", first, cut), ("FWD", cut, last + 1)):
            trades, _ = bt._window_trades(bars, t0, t1, 100.0)
            rule = [t for t in trades if t.reason != "WINDOW_MARK"]
            pn = [t.pnl for t in rule]
            marks = sum(t.pnl for t in trades if t.reason == "WINDOW_MARK")
            avg = statistics.mean(pn) if pn else 0.0
            se = statistics.stdev(pn) / len(pn) ** 0.5 if len(pn) > 1 else 0.0
            mix = [t.pnl for t in rule if t.used_long1 or t.used_long2]
            row.append(
                f"{label} n={len(pn):4d} avg={avg:+.2f}±{se:.2f} sum={sum(pn):+8.1f} "
                f"mix={sum(mix):+8.1f}/{len(mix)} openmark={marks:+7.1f}"
            )
        print(" | ".join(row), flush=True)
    svr._apply({})


if __name__ == "__main__":
    main()
