"""
Walk-forward variant research for short_first_v1 on the live-like pump universe.

1. Universe: every TRADING USDT perpetual >= $10M 24h quote volume, ranked by how often it
   printed a >=5% 15m pump in the TRAIN window only (no forward look-ahead).
2. 1m klines cached under .bt_cache/ (public mainnet data; never touches the VPS IP).
3. Each variant patches run_short_first_backtest module knobs, replays train + held-out
   forward, one trade at a time, $100 partition.

  python strategy_variant_research.py --days 60 --forward 30 --top 60
"""

from __future__ import annotations

import argparse
import json
import pickle
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import run_short_first_backtest as bt  # noqa: E402
from momentum_scanner import MIN_QUOTE_VOL_24H  # noqa: E402
from run_exhaustion_backtest import FAPI, _get, fetch_klines_days  # noqa: E402

CACHE = _HERE / ".bt_cache"

KNOBS = (
    "GAIN_THRESHOLD_PCT",
    "RETRACE_ENTRY_PCT",
    "LONG1_ADVERSE_PCT",
    "LONG2_ADVERSE_PCT",
    "PAIR_INVALIDATION_PCT",
    "SHORT_TP_PCT",
    "LONG_TP_PCT",
    "SMART_EXIT_PCT",
    "MIN_LIVE_ENTRY",
    "SHORT_TRAIL_MFE",
    "MAX_RETRACE",
    "HEDGED_PAIR_STOP_USD",
    "HEDGED_MAX_HOLD_MIN",
)
BASE = {k: getattr(bt, k) for k in KNOBS}
OFF = 999.0


def _variants_pair() -> dict[str, dict[str, Any]]:
    """Phase 2: downside exit for the net-long hedged pair, on top of frozen knobs."""
    v: dict[str, dict[str, Any]] = {"baseline": {}}
    for stop in (None, 4.0, 6.0, 8.0, 10.0, 12.0, 16.0):
        for hold in (None, 120, 240, 480, 720, 1440):
            if stop is None and hold is None:
                continue
            name = f"stop{stop:g}" if stop is not None else "stopNA"
            name += f"_hold{hold}" if hold is not None else "_holdNA"
            ov: dict[str, Any] = {}
            if stop is not None:
                ov["HEDGED_PAIR_STOP_USD"] = stop
            if hold is not None:
                ov["HEDGED_MAX_HOLD_MIN"] = hold
            v[name] = ov
    return v


def _variants_entry() -> dict[str, dict[str, Any]]:
    """Phase 3: entry quality under exits that actually realize (no weeks-long stuck pair)."""
    exits: dict[str, dict[str, Any]] = {
        "hedged_hold24h": {"HEDGED_MAX_HOLD_MIN": 1440},
        "hedged_hold8h": {"HEDGED_MAX_HOLD_MIN": 480},
        "naked_inv6.5": {"LONG1_ADVERSE_PCT": OFF, "LONG2_ADVERSE_PCT": OFF},
        "naked_stop4": {"LONG1_ADVERSE_PCT": OFF, "LONG2_ADVERSE_PCT": OFF, "PAIR_INVALIDATION_PCT": 4.0},
    }
    v: dict[str, dict[str, Any]] = {}
    for g in (5.0, 7.0, 10.0, 15.0):
        for r in (0.7, 1.5, 3.0, 5.0):
            for en, ex in exits.items():
                v[f"g{g:g}_r{r:g}_{en}"] = {"GAIN_THRESHOLD_PCT": g, "RETRACE_ENTRY_PCT": r, **ex}
    return v


def _variants_fine() -> dict[str, dict[str, Any]]:
    """Phase 4: neighborhood around the deep-retrace region (robustness, not a single best cell)."""
    v: dict[str, dict[str, Any]] = {}
    for g in (5.0, 6.0, 7.0):
        for r in (3.5, 4.0, 5.0, 6.0, 7.0):
            for hold in (None, 720, 1440, 2880):
                ov: dict[str, Any] = {"GAIN_THRESHOLD_PCT": g, "RETRACE_ENTRY_PCT": r}
                if hold is not None:
                    ov["HEDGED_MAX_HOLD_MIN"] = hold
                v[f"g{g:g}_r{r:g}_hold{hold or 'NA'}"] = ov
    return v


def _variants() -> dict[str, dict[str, float]]:
    v: dict[str, dict[str, float]] = {"baseline": {}}
    for g in (5.0, 6.0, 7.0, 8.0):
        tag = f"g{g:g}"
        if g != 5.0:
            v[f"{tag}_hedged"] = {"GAIN_THRESHOLD_PCT": g}
        for stop in (2.0, 3.0, 4.0):
            v[f"{tag}_naked_stop{stop:g}"] = {
                "GAIN_THRESHOLD_PCT": g,
                "LONG1_ADVERSE_PCT": OFF,
                "LONG2_ADVERSE_PCT": OFF,
                "PAIR_INVALIDATION_PCT": stop,
            }
        v[f"{tag}_l1only_inv5"] = {
            "GAIN_THRESHOLD_PCT": g,
            "LONG2_ADVERSE_PCT": OFF,
            "PAIR_INVALIDATION_PCT": 5.0,
        }
    for tp in (1.5, 2.0, 3.0):
        v[f"g5_hedged_tp{tp:g}"] = {"SHORT_TP_PCT": tp}
        v[f"g6_naked_stop3_tp{tp:g}"] = {
            "GAIN_THRESHOLD_PCT": 6.0,
            "LONG1_ADVERSE_PCT": OFF,
            "LONG2_ADVERSE_PCT": OFF,
            "PAIR_INVALIDATION_PCT": 3.0,
            "SHORT_TP_PCT": tp,
        }
    for r in (1.0, 1.5):
        v[f"g5_hedged_retr{r:g}"] = {"RETRACE_ENTRY_PCT": r}
        v[f"g6_naked_stop3_retr{r:g}"] = {
            "GAIN_THRESHOLD_PCT": 6.0,
            "LONG1_ADVERSE_PCT": OFF,
            "LONG2_ADVERSE_PCT": OFF,
            "PAIR_INVALIDATION_PCT": 3.0,
            "RETRACE_ENTRY_PCT": r,
        }
    return v


def _apply(overrides: dict[str, float]) -> None:
    for k in KNOBS:
        setattr(bt, k, overrides.get(k, BASE[k]))


def _liquid_symbols() -> list[str]:
    info = _get(f"{FAPI}/fapi/v1/exchangeInfo")
    live = {
        s["symbol"]
        for s in info.get("symbols", [])
        if s.get("quoteAsset") == "USDT"
        and s.get("contractType") == "PERPETUAL"
        and s.get("status") == "TRADING"
    }
    tick = _get(f"{FAPI}/fapi/v1/ticker/24hr")
    vol = {t["symbol"]: float(t.get("quoteVolume") or 0) for t in tick}
    return sorted(s for s in live if vol.get(s, 0) + 1e-9 >= MIN_QUOTE_VOL_24H)


def _cached(name: str, fn):
    CACHE.mkdir(exist_ok=True)
    p = CACHE / name
    if p.exists():
        return pickle.loads(p.read_bytes())
    out = fn()
    p.write_bytes(pickle.dumps(out))
    return out


def _pump_count(bars15: list[dict], t0: int, t1: int, thr: float) -> int:
    n = 0
    last = -10**18
    for i in range(1, len(bars15)):
        b = bars15[i]
        if not (t0 <= b["t"] < t1):
            continue
        prev = bars15[i - 1]["c"]
        if prev > 0 and (b["h"] - prev) / prev * 100.0 >= thr and b["t"] - last > 3_600_000:
            n += 1
            last = b["t"]
    return n


def _fetch_many(symbols: list[str], interval: str, days: int, tag: str) -> dict[str, list[dict]]:
    def one(sym: str):
        try:
            return sym, _cached(f"{sym}_{interval}_{days}d_{tag}.pkl", lambda: fetch_klines_days(sym, interval, days))
        except Exception as e:  # noqa: BLE001
            print(f"  fetch fail {sym}: {e}", flush=True)
            return sym, []

    out: dict[str, list[dict]] = {}
    with ThreadPoolExecutor(max_workers=3) as ex:
        for n, (sym, bars) in enumerate(ex.map(one, symbols), 1):
            if bars:
                out[sym] = bars
            if n % 10 == 0:
                print(f"  {interval} {n}/{len(symbols)}", flush=True)
    return out


def _run(bars_by_sym, t0, t1, partition, equity) -> dict[str, Any]:
    trades, _ = bt._window_trades(bars_by_sym, t0, t1, partition)
    packed = bt._pack("w", trades, partition, equity, t0, t1)
    s = packed["summary"]
    kept = packed["trades"]
    mix = [t for t in kept if t["l1"] or t["l2"]]
    naked = [t for t in kept if not (t["l1"] or t["l2"])]
    days = s["window_days"]
    daily: dict[str, float] = {}
    for t in kept:
        d = time.strftime("%Y-%m-%d", time.gmtime(t["exit_t"] / 1000))
        daily[d] = round(daily.get(d, 0.0) + t["pnl"], 2)
    return {
        "trades": s["trades"],
        "trades_per_day": s["trades_per_day"],
        "win_rate": s["win_rate"],
        "net_pnl": s["net_pnl"],
        "pnl_per_day": round(s["net_pnl"] / days, 2) if days else 0.0,
        "avg_win": s["avg_win"],
        "avg_loss": s["avg_loss"],
        "max_dd_pct_of_100": s["max_dd"],
        "mix_n": len(mix),
        "mix_pnl": round(sum(t["pnl"] for t in mix), 2),
        "naked_n": len(naked),
        "naked_pnl": round(sum(t["pnl"] for t in naked), 2),
        "by_reason": packed["per_reason_pnl"],
        "green_days": sum(1 for v in daily.values() if v > 0),
        "red_days": sum(1 for v in daily.values() if v <= 0),
        "daily": daily,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--forward", type=int, default=30)
    ap.add_argument("--top", type=int, default=60)
    ap.add_argument("--tag", type=str, default=time.strftime("%Y%m%d", time.gmtime()))
    ap.add_argument("--only", type=str, default="")
    ap.add_argument("--phase", type=str, default="grid", choices=("grid", "pair", "entry", "fine"))
    ap.add_argument("--out", type=str, default=str(_HERE / "strategy_variant_research.json"))
    args = ap.parse_args()
    partition = 100.0
    equity = 100.0

    syms = _cached(f"universe_{args.tag}.pkl", _liquid_symbols)
    print(f"liquid USDT perps >= ${MIN_QUOTE_VOL_24H:,.0f}: {len(syms)}", flush=True)
    b15 = _fetch_many(syms, "15m", args.days, args.tag)
    last_t = max(b[-1]["t"] for b in b15.values() if b)
    first_t = last_t - args.days * 86_400_000
    cut = last_t - args.forward * 86_400_000
    ranked = sorted(
        ((s, _pump_count(b, first_t, cut, 5.0)) for s, b in b15.items()),
        key=lambda kv: kv[1],
        reverse=True,
    )
    universe = [s for s, n in ranked[: args.top] if n > 0]
    print("universe (train-window 15m pump count):", [(s, n) for s, n in ranked[: args.top]], flush=True)

    b1 = _fetch_many(universe, "1m", args.days, args.tag)
    last_1m = max(b[-1]["t"] for b in b1.values() if b)
    first_1m = min(b[0]["t"] for b in b1.values() if b)
    cut = last_1m - args.forward * 86_400_000
    print(
        f"train {time.strftime('%Y-%m-%d', time.gmtime(first_1m / 1000))} -> "
        f"{time.strftime('%Y-%m-%d', time.gmtime(cut / 1000))} | forward -> "
        f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(last_1m / 1000))}",
        flush=True,
    )

    results: dict[str, Any] = {}
    variants = {"pair": _variants_pair, "entry": _variants_entry, "fine": _variants_fine}.get(args.phase, _variants)()
    if args.only:
        keep = {x.strip() for x in args.only.split(",")}
        variants = {k: v for k, v in variants.items() if k in keep}
    for name, ov in variants.items():
        _apply(ov)
        t = time.perf_counter()
        tr = _run(b1, first_1m, cut, partition, equity)
        fw = _run(b1, cut, last_1m + 1, partition, equity)
        results[name] = {"overrides": ov, "train": tr, "forward": fw}
        print(
            f"{name:28s} TRAIN n={tr['trades']:4d} {tr['trades_per_day']:5.1f}/d wr={tr['win_rate']:5.1f} "
            f"net={tr['net_pnl']:8.2f} dd={tr['max_dd_pct_of_100']:6.1f} | FWD n={fw['trades']:4d} "
            f"{fw['trades_per_day']:5.1f}/d wr={fw['win_rate']:5.1f} net={fw['net_pnl']:8.2f} "
            f"dd={fw['max_dd_pct_of_100']:6.1f} mix={fw['mix_pnl']:7.2f}/{fw['mix_n']} "
            f"naked={fw['naked_pnl']:7.2f}/{fw['naked_n']}  ({time.perf_counter() - t:.0f}s)",
            flush=True,
        )
    _apply({})
    Path(args.out).write_text(
        json.dumps(
            {
                "universe": universe,
                "train_from": first_1m,
                "cut": cut,
                "forward_to": last_1m,
                "partition_usd": partition,
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
