"""
Backtest live short_first_v1 (frozen contract) on $100 partition.

Same window/symbols as exhaustion research for apples-to-apples comparison.
Does NOT change live trading.

  python run_short_first_backtest.py --days 45 --partition 100 --equity 100
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from frozen_strategy import (
    GAIN_THRESHOLD_PCT,
    HEDGED_MAX_HOLD_MS,
    LONG1_ADVERSE_PCT,
    LONG2_ADVERSE_PCT,
    LONG_HEDGE_PULLBACK_PCT,
    LONG_TP_PCT,
    PRIMARY_LEVERAGE,
    PRIMARY_PARTITION_PCT,
    RECOVERY_LEVERAGE,
    RECOVERY_PARTITION_PCT,
    RETRACE_ENTRY_PCT,
    SHORT_TP_PCT,
    SHORT_TRAIL_PULLBACK_FLOOR_PCT,
)
from momentum_scanner import (
    ENTRY_COOLDOWN_MS,
    EPISODE_COOLDOWN_MS,
    INVALIDATION_COOLDOWN_MS,
    MIN_QUOTE_VOL_24H,
)
from run_exhaustion_backtest import fetch_klines_days

FEE_RATE = 0.0004
SLIP_PCT = 0.05
MAX_RETRACE = 12.0
MIN_LIVE_ENTRY = 2.0
SMART_EXIT_PCT = 6.0
EXIT_COST_PCT = 0.8
SHORT_TRAIL_MFE = 1.5
PAIR_INVALIDATION_PCT = 6.5
HEDGE_RESCUE_BUFFER_PCT = 1.0
MAX_HOLD_BARS_1M = 24 * 60  # ~24h on 1m
# Research override for a USD pair stop (None = off). Live uses PAIR_TIME instead.
HEDGED_PAIR_STOP_USD: float | None = None
# Live frozen: PAIR_TIME after hedge episode (ms → 1m bars). Override to None to disable.
HEDGED_MAX_HOLD_MIN: int | None = max(1, int(HEDGED_MAX_HOLD_MS // 60_000))
DEFAULT_INTERVAL = "1m"


def _cooldown_ms_for_reason(reason: str) -> int:
    """Match live desk-quality cool-offs (INVALIDATION 20m, rescue/orphan 10m, else 5m)."""
    r = (reason or "").upper()
    if "INVALIDATION" in r:
        return max(ENTRY_COOLDOWN_MS, INVALIDATION_COOLDOWN_MS)
    if any(x in r for x in ("ORPHAN", "SHORT_GONE", "RESCUE", "PAIR_FLATTEN", "PAIR_STOP", "PAIR_TIME")):
        return max(ENTRY_COOLDOWN_MS, EPISODE_COOLDOWN_MS)
    return max(0, ENTRY_COOLDOWN_MS)


@dataclass
class Leg:
    side: str
    entry: float
    margin: float
    lev: int
    qty: float
    tp: float | None = None
    peak: float | None = None
    trough: float | None = None


@dataclass
class Trade:
    symbol: str
    entry_t: int
    entry_px: float
    exit_t: int = 0
    exit_px: float = 0.0
    reason: str = ""
    pnl: float = 0.0
    used_long1: bool = False
    used_long2: bool = False
    max_adverse_pct: float = 0.0
    mfe_pct: float = 0.0


def _fees(notional: float) -> float:
    return abs(notional) * (FEE_RATE + SLIP_PCT / 100.0)


def _pnl(leg: Leg, px: float) -> float:
    if leg.side == "SELL":
        return (leg.entry - px) * leg.qty
    return (px - leg.entry) * leg.qty


# Live scanner rolls 15 minutes of marks. On 1m bars that is exactly 15 bars back.
ROLL_15M_BARS = 15


def _pct_roll_close(bars: list[dict], i: int, look: int = ROLL_15M_BARS) -> float:
    """Factual rolling N-minute % at bar close (matches scanner _rolling_pcts on 1m marks)."""
    j = i - look
    if j < 0:
        return 0.0
    old = float(bars[j]["c"])
    if old <= 0:
        return 0.0
    return (float(bars[i]["c"]) - old) / old * 100.0


def _pct_roll_high(bars: list[dict], i: int, look: int = ROLL_15M_BARS) -> float:
    """Max traded rolling % using this bar's high vs close N bars ago."""
    j = i - look
    if j < 0:
        return 0.0
    old = float(bars[j]["c"])
    if old <= 0:
        return 0.0
    return (float(bars[i]["h"]) - old) / old * 100.0


def simulate_symbol(
    symbol: str,
    bars: list[dict],
    partition: float,
    max_hold_bars: int | None = MAX_HOLD_BARS_1M,
) -> list[Trade]:
    """Factual 1m bar replay — no invented wick path, no random fills.

    Entry: rolling 15m % from closes 15 bars apart (same math as live _rolling_pcts);
    latch when high-print rolling % >= 5%; enter on close when retrace 0.7–12% and
    live close still hot. Manage on 1m close; H/L only prove touch. Same-bar
    conflict = adverse-first (inv/hedge before TP).
    """
    short_m = partition * PRIMARY_PARTITION_PCT / 100.0
    l1_m = partition * RECOVERY_PARTITION_PCT / 100.0
    l2_m = partition * RECOVERY_PARTITION_PCT / 100.0
    smart_target = partition * SMART_EXIT_PCT / 100.0 + partition * EXIT_COST_PCT / 100.0

    trades: list[Trade] = []
    i = ROLL_15M_BARS + 2
    cooldown_until = 0
    latched = False
    latch_peak = 0.0
    latch_pct = 0.0

    while i < len(bars) - 1:
        if bars[i]["t"] < cooldown_until:
            latched = False
            i += 1
            continue

        live_close = _pct_roll_close(bars, i)
        live_high = _pct_roll_high(bars, i)
        hi = float(bars[i]["h"])
        close = float(bars[i]["c"])

        if not latched:
            if live_high >= GAIN_THRESHOLD_PCT:
                latched = True
                latch_peak = hi
                latch_pct = max(live_high, live_close)
            i += 1
            continue

        latch_peak = max(latch_peak, hi)
        latch_pct = max(latch_pct, live_high, live_close)
        retrace = (latch_peak - close) / latch_peak * 100.0 if latch_peak > 0 else 0.0
        live_floor = max(MIN_LIVE_ENTRY, latch_pct * 0.45)
        signal_ok = (
            RETRACE_ENTRY_PCT <= retrace <= MAX_RETRACE
            and live_close >= MIN_LIVE_ENTRY
            and live_close >= live_floor
        )
        if not signal_ok:
            if live_close < MIN_LIVE_ENTRY or retrace > MAX_RETRACE:
                latched = False
            i += 1
            continue

        entry_i = i
        entry_px = close * (1.0 - SLIP_PCT / 100.0)
        short_qty = (short_m * PRIMARY_LEVERAGE) / entry_px
        short = Leg(
            "SELL",
            entry_px,
            short_m,
            PRIMARY_LEVERAGE,
            short_qty,
            tp=entry_px * (1 - SHORT_TP_PCT / 100.0),
            trough=entry_px,
        )
        long1: Leg | None = None
        long2: Leg | None = None
        long1_done = False
        long2_done = False
        fees = _fees(short_m * PRIMARY_LEVERAGE)
        realized = 0.0
        trade = Trade(symbol=symbol, entry_t=bars[entry_i]["t"], entry_px=entry_px)
        latched = False

        def _book(px: float) -> tuple[float, float, float, bool]:
            upnl = _pnl(short, px)
            if long1:
                upnl += _pnl(long1, px)
            if long2:
                upnl += _pnl(long2, px)
            short_pnl = _pnl(short, px)
            return upnl, short_pnl, upnl - short_pnl, px >= entry_px - 1e-12

        def _arm(which: int, touch: float) -> None:
            nonlocal long1, long2, fees
            if which == 1:
                l1e = entry_px * (1 + LONG1_ADVERSE_PCT / 100.0)
                long1 = Leg(
                    "BUY",
                    l1e,
                    l1_m,
                    RECOVERY_LEVERAGE,
                    (l1_m * RECOVERY_LEVERAGE) / l1e,
                    tp=l1e * (1 + LONG_TP_PCT / 100.0),
                    peak=max(l1e, touch),
                )
                fees += _fees(l1_m * RECOVERY_LEVERAGE)
                trade.used_long1 = True
            else:
                l2e = entry_px * (1 + LONG2_ADVERSE_PCT / 100.0)
                long2 = Leg(
                    "BUY",
                    l2e,
                    l2_m,
                    RECOVERY_LEVERAGE,
                    (l2_m * RECOVERY_LEVERAGE) / l2e,
                    tp=l2e * (1 + LONG_TP_PCT / 100.0),
                    peak=max(l2e, touch),
                )
                fees += _fees(l2_m * RECOVERY_LEVERAGE)
                trade.used_long2 = True

        hold_end = len(bars) if max_hold_bars is None else min(entry_i + max_hold_bars, len(bars))
        exit_reason = ""
        exit_i = entry_i
        exit_px = entry_px
        stopped = False

        for j in range(entry_i + 1, hold_end):
            bar = bars[j]
            px = float(bar["c"])
            hi_b = float(bar["h"])
            lo_b = float(bar["l"])
            # Adverse from high (level was traded); trough from low.
            adverse_hi = (hi_b - entry_px) / entry_px * 100.0
            trade.max_adverse_pct = max(trade.max_adverse_pct, adverse_hi)
            if short.trough is None or lo_b < short.trough:
                short.trough = lo_b
            mfe = (entry_px - float(short.trough)) / entry_px * 100.0
            trade.mfe_pct = max(trade.mfe_pct, mfe)

            # 1) Adverse-first: arm / invalidate from high before rewarding short TP on low.
            if (
                long1 is None
                and not long1_done
                and LONG1_ADVERSE_PCT <= adverse_hi < PAIR_INVALIDATION_PCT
            ):
                _arm(1, hi_b)
            if (
                long2 is None
                and not long2_done
                and LONG2_ADVERSE_PCT <= adverse_hi < PAIR_INVALIDATION_PCT
            ):
                _arm(2, hi_b)
            if long1 and (long1.peak is None or hi_b > long1.peak):
                long1.peak = hi_b
            if long2 and (long2.peak is None or hi_b > long2.peak):
                long2.peak = hi_b

            if adverse_hi >= PAIR_INVALIDATION_PCT:
                # Live exits on the tick that crosses the level, not on the 1m close.
                inv_px = entry_px * (1 + PAIR_INVALIDATION_PCT / 100.0)
                exit_px, exit_i, exit_reason, stopped = inv_px, j, "INVALIDATION", True
                break

            upnl, short_pnl, long_pnl, underwater = _book(px)
            hedge_episode = (
                long1 is not None
                or long2 is not None
                or long1_done
                or long2_done
                or trade.max_adverse_pct + 1e-12 >= LONG1_ADVERSE_PCT
            )
            rescue_buf = partition * HEDGE_RESCUE_BUFFER_PCT / 100.0
            if (long1 or long2) and short_pnl < 0 and long_pnl >= (-short_pnl) + rescue_buf:
                exit_px, exit_i, exit_reason, stopped = px, j, "RESCUE", True
                break

            if (long1 or long2) and HEDGED_PAIR_STOP_USD is not None:
                if upnl + realized <= -float(HEDGED_PAIR_STOP_USD):
                    exit_px, exit_i, exit_reason, stopped = px, j, "PAIR_STOP", True
                    break
            if hedge_episode and HEDGED_MAX_HOLD_MIN is not None and (j - entry_i) >= int(HEDGED_MAX_HOLD_MIN):
                exit_px, exit_i, exit_reason, stopped = px, j, "PAIR_TIME", True
                break

            hedges_open = bool(long1 or long2)
            short_ok_for_smart = (not hedges_open) or (not underwater)
            if (
                upnl >= smart_target
                and short_ok_for_smart
                and not (
                    long1 is None
                    and long2 is None
                    and not long1_done
                    and trade.max_adverse_pct < LONG1_ADVERSE_PCT
                )
            ):
                exit_px, exit_i, exit_reason, stopped = px, j, "SMART_EXIT", True
                break

            # Solo hedge exits only pre-episode while short green — mark = close.
            solo_hedge_ok = (not underwater) and (not hedge_episode)
            if solo_hedge_ok:
                if long1:
                    if long1.tp and hi_b >= long1.tp:
                        realized += _pnl(long1, long1.tp)
                        fees += _fees(long1.margin * long1.lev)
                        long1 = None
                        long1_done = True
                    else:
                        pb = (
                            (float(long1.peak) - lo_b) / float(long1.peak) * 100.0
                            if long1.peak
                            else 0.0
                        )
                        if pb >= LONG_HEDGE_PULLBACK_PCT:
                            realized += _pnl(
                                long1,
                                max(lo_b, float(long1.peak) * (1 - LONG_HEDGE_PULLBACK_PCT / 100.0)),
                            )
                            fees += _fees(long1.margin * long1.lev)
                            long1 = None
                            long1_done = True
                if long2:
                    if long2.tp and hi_b >= long2.tp:
                        realized += _pnl(long2, long2.tp)
                        fees += _fees(long2.margin * long2.lev)
                        long2 = None
                        long2_done = True
                    else:
                        pb = (
                            (float(long2.peak) - lo_b) / float(long2.peak) * 100.0
                            if long2.peak
                            else 0.0
                        )
                        if pb >= LONG_HEDGE_PULLBACK_PCT:
                            realized += _pnl(
                                long2,
                                max(lo_b, float(long2.peak) * (1 - LONG_HEDGE_PULLBACK_PCT / 100.0)),
                            )
                            fees += _fees(long2.margin * long2.lev)
                            long2 = None
                            long2_done = True

            # Live _hedged_short_exit_net_ok: hedged SHORT_TP only when net clears cost buffer.
            cost_buf = partition * EXIT_COST_PCT / 100.0
            if short.tp and lo_b <= short.tp:
                upnl_tp, _, _, _ = _book(short.tp)
                hedges_now = bool(long1 or long2)
                if (not hedges_now) or (upnl_tp >= cost_buf):
                    exit_px, exit_i, exit_reason, stopped = short.tp, j, "SHORT_TP", True
                    break
                # else: paired hold until RESCUE / INVALIDATION / SMART_EXIT

            upnl, _, _, _ = _book(px)
            recovery_eligible = (long1 is None and not long1_done) or (
                long2 is None and not long2_done
            )
            naked_can_still_hedge = recovery_eligible and long1 is None and long2 is None
            longs_open = bool(long1 or long2)
            cost_ok = (not longs_open) or (upnl >= cost_buf)
            if (
                mfe >= SHORT_TRAIL_MFE
                and short.trough
                and px < entry_px
                and not naked_can_still_hedge
                and cost_ok
            ):
                bounce = (px - float(short.trough)) / float(short.trough) * 100.0
                if bounce >= SHORT_TRAIL_PULLBACK_FLOOR_PCT:
                    exit_px, exit_i, exit_reason, stopped = px, j, "SHORT_TRAIL", True
                    break

        if not stopped:
            if max_hold_bars is None:
                exit_i = len(bars) - 1
                exit_px = bars[exit_i]["c"]
                exit_reason = "WINDOW_MARK"
            else:
                exit_i = min(entry_i + max_hold_bars - 1, len(bars) - 1)
                exit_px = bars[exit_i]["c"]
                exit_reason = "MAX_HOLD"

        pnl = _pnl(short, exit_px)
        fees += _fees(short_m * PRIMARY_LEVERAGE)
        if long1:
            pnl += _pnl(long1, exit_px)
            fees += _fees(long1.margin * long1.lev)
        if long2:
            pnl += _pnl(long2, exit_px)
            fees += _fees(long2.margin * long2.lev)
        pnl += realized - fees

        trade.exit_t = bars[exit_i]["t"]
        trade.exit_px = exit_px
        trade.reason = exit_reason
        trade.pnl = round(pnl, 4)
        trades.append(trade)
        cooldown_until = trade.exit_t + _cooldown_ms_for_reason(exit_reason)
        i = exit_i + 1

    return trades


def summarize(trades: list[Trade], partition: float, equity0: float) -> dict[str, Any]:
    equity = equity0
    curve = [{"i": 0, "equity": equity}]
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    for n, t in enumerate(trades, 1):
        equity += t.pnl
        curve.append({"i": n, "equity": round(equity, 2), "symbol": t.symbol, "pnl": t.pnl})
    by_reason: dict[str, int] = {}
    for t in trades:
        by_reason[t.reason] = by_reason.get(t.reason, 0) + 1
    gross = sum(t.pnl for t in trades)
    return {
        "strategy": "short_first_v1",
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
        "net_pnl": round(gross, 2),
        "avg_pnl": round(gross / len(trades), 2) if trades else 0.0,
        "avg_win": round(sum(t.pnl for t in wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(t.pnl for t in losses) / len(losses), 2) if losses else 0.0,
        "max_dd": _max_dd(curve),
        "end_equity": round(equity, 2),
        "start_equity": equity0,
        "partition_usd": partition,
        "by_reason": by_reason,
        "equity_curve": curve,
        "hedge_rate_l1": round(sum(1 for t in trades if t.used_long1) / len(trades) * 100, 1)
        if trades
        else 0,
        "hedge_rate_l2": round(sum(1 for t in trades if t.used_long2) / len(trades) * 100, 1)
        if trades
        else 0,
    }


def _max_dd(curve: list[dict]) -> float:
    peak = curve[0]["equity"]
    dd = 0.0
    for p in curve:
        peak = max(peak, p["equity"])
        if peak > 0:
            dd = max(dd, (peak - p["equity"]) / peak * 100.0)
    return round(dd, 2)


def _one_at_a_time(trades: list[Trade]) -> tuple[list[Trade], int]:
    ordered = sorted(trades, key=lambda t: t.entry_t)
    kept: list[Trade] = []
    busy_until = 0
    for t in ordered:
        if t.entry_t < busy_until:
            continue
        kept.append(t)
        busy_until = t.exit_t
    return kept, len(ordered) - len(kept)


def _window_trades(
    bars_by_sym: dict[str, list[dict]],
    t0: int,
    t1: int,
    partition: float,
) -> tuple[list[Trade], dict[str, Any]]:
    """Replay each symbol on bars inside [t0, t1). No artificial 24h time-stop."""
    all_trades: list[Trade] = []
    per_symbol: dict[str, Any] = {}
    for sym, bars in bars_by_sym.items():
        window = [b for b in bars if t0 <= b["t"] < t1]
        if len(window) < 30:
            per_symbol[sym] = {"error": f"only {len(window)} bars"}
            continue
        tr = [
            t
            for t in simulate_symbol(sym, window, partition, max_hold_bars=None)
            if t0 <= t.entry_t < t1
        ]
        per_symbol[sym] = {
            "trades": len(tr),
            "pnl": round(sum(t.pnl for t in tr), 2),
            "bars": len(window),
            "l1": sum(1 for t in tr if t.used_long1),
            "l2": sum(1 for t in tr if t.used_long2),
        }
        all_trades.extend(tr)
    return all_trades, per_symbol


def _pack(label: str, trades: list[Trade], partition: float, equity0: float, t0: int, t1: int) -> dict[str, Any]:
    kept, skipped = _one_at_a_time(trades)
    summary = summarize(kept, partition, equity0)
    summary["skipped_overlap"] = skipped
    window_days = max(1e-9, (t1 - t0) / 86_400_000.0)
    summary["window_days"] = round(window_days, 4)
    summary["trades_per_day"] = round(len(kept) / window_days, 2)
    summary["raw_candidates"] = len(trades)
    summary["raw_candidates_per_day"] = round(len(trades) / window_days, 2)
    if kept:
        holds_h = [(t.exit_t - t.entry_t) / 3_600_000.0 for t in kept]
        summary["avg_hold_hours"] = round(sum(holds_h) / len(holds_h), 2)
        summary["median_hold_hours"] = round(sorted(holds_h)[len(holds_h) // 2], 2)
    else:
        summary["avg_hold_hours"] = 0.0
        summary["median_hold_hours"] = 0.0
    rule = [t for t in kept if t.reason != "WINDOW_MARK"]
    marks = [t for t in kept if t.reason == "WINDOW_MARK"]
    summary["rule_exits"] = len(rule)
    summary["window_marks"] = len(marks)
    summary["rule_net_pnl"] = round(sum(t.pnl for t in rule), 2)
    summary["window_mark_pnl"] = round(sum(t.pnl for t in marks), 2)
    return {
        "label": label,
        "from_ms": t0,
        "to_ms": t1,
        "from_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(t0 / 1000)),
        "to_utc": time.strftime("%Y-%m-%d %H:%M", time.gmtime(t1 / 1000)),
        "summary": summary,
        "per_reason_pnl": _reason_pnl(kept),
        "trades": [
            {
                "symbol": t.symbol,
                "entry_t": t.entry_t,
                "exit_t": t.exit_t,
                "pnl": t.pnl,
                "reason": t.reason,
                "l1": t.used_long1,
                "l2": t.used_long2,
                "mae": round(t.max_adverse_pct, 2),
                "mfe": round(t.mfe_pct, 2),
            }
            for t in kept
        ],
    }


def _reason_pnl(trades: list[Trade]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for t in trades:
        slot = out.setdefault(t.reason, {"n": 0, "pnl": 0.0})
        slot["n"] += 1
        slot["pnl"] = round(slot["pnl"] + t.pnl, 2)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=45)
    ap.add_argument("--symbols", type=str, default="")
    ap.add_argument(
        "--top",
        type=int,
        default=0,
        help="Top N USDT-M by 24h quote volume above liquidity floor (0 = fixed liquid set)",
    )
    ap.add_argument("--partition", type=float, default=100.0)
    ap.add_argument(
        "--equity",
        type=float,
        default=100.0,
        help="Starting equity for DD curve (desk sub-partition default $100)",
    )
    ap.add_argument("--walk-forward", type=int, default=0, help="Hold out the latest N days as forward")
    ap.add_argument("--no-time-stop", action="store_true")
    ap.add_argument(
        "--out",
        type=str,
        default=str(_HERE / "short_first_backtest_result.json"),
    )
    args = ap.parse_args()

    from frozen_strategy import LOCKED_PARTITION_USD, assert_frozen_contract
    from run_exhaustion_backtest import _get

    contract = assert_frozen_contract()
    if abs(float(args.partition) - LOCKED_PARTITION_USD) > 1e-9:
        print(f"partition forced to locked ${LOCKED_PARTITION_USD} (arg was {args.partition})")
        args.partition = LOCKED_PARTITION_USD

    # Fixed liquid universe — no look-ahead from "today's top volume" ranking.
    # Names that have persistently cleared the $10M desk floor on USD-M.
    FIXED_LIQUID = [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "XRPUSDT",
        "DOGEUSDT",
        "LINKUSDT",
        "AVAXUSDT",
        "NEARUSDT",
        "SUIUSDT",
        "APTUSDT",
        "ARBUSDT",
        "OPUSDT",
        "INJUSDT",
        "TIAUSDT",
        "ENAUSDT",
        "WIFUSDT",
        "1000PEPEUSDT",
        "ZECUSDT",
    ]
    tickers = _get("https://fapi.binance.com/fapi/v1/ticker/24hr")
    vol_map: dict[str, float] = {}
    for t in tickers or []:
        sym = str(t.get("symbol") or "").upper()
        if sym.endswith("USDT"):
            vol_map[sym] = float(t.get("quoteVolume") or 0.0)

    if args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    elif args.top > 0:
        # Live desk scans the liquid book (FORWARD_MAX_SYMBOLS≈40), not majors-only.
        ranked = sorted(
            (
                (sym, vol)
                for sym, vol in vol_map.items()
                if sym.endswith("USDT") and vol + 1e-9 >= MIN_QUOTE_VOL_24H
            ),
            key=lambda kv: kv[1],
            reverse=True,
        )
        symbols = [sym for sym, _ in ranked[: max(1, int(args.top))]]
    else:
        symbols = list(FIXED_LIQUID)
    # Enforce live liquidity floor (desk gate) — drop only if we have a vol reading below floor.
    kept: list[str] = []
    for s in symbols:
        v = vol_map.get(s)
        if v is None:
            kept.append(s)  # keep if ticker missing; fetch will fail loudly if delisted
        elif v + 1e-9 >= MIN_QUOTE_VOL_24H:
            kept.append(s)
        else:
            print(f"  drop {s} vol24h={v:,.0f} < floor {MIN_QUOTE_VOL_24H:,.0f}")
    symbols = kept
    if abs(float(args.equity) - float(args.partition)) > 1e-9:
        print(
            f"note: equity=${args.equity} vs locked partition=${args.partition} "
            f"(DD curve uses equity; sizing always uses partition)"
        )
    print(
        f"short_first_v1 FACTUAL | symbols={len(symbols)} | {args.days}d | "
        f"partition=${args.partition} | equity=${args.equity} | walk={args.walk_forward}"
    )
    print(
        f"method=close-based+adverse-first | liquidity_floor=${MIN_QUOTE_VOL_24H:,.0f} | "
        f"inv_cool_s={INVALIDATION_COOLDOWN_MS // 1000} | ep_cool_s={EPISODE_COOLDOWN_MS // 1000}"
    )
    print("symbols:", ",".join(symbols))
    for s in symbols:
        print(f"  vol24h {s}={vol_map.get(s, 0):,.0f}")

    if args.walk_forward > 0:
        if args.walk_forward >= args.days:
            print("walk-forward days must be shorter than the full window")
            return 2
        bars_by_sym: dict[str, list[dict]] = {}
        for sym in symbols:
            print(f"  fetch {sym} ...", flush=True)
            try:
                bars_by_sym[sym] = fetch_klines_days(sym, DEFAULT_INTERVAL, args.days)
                print(f"    {len(bars_by_sym[sym])} {DEFAULT_INTERVAL} bars")
            except Exception as e:  # noqa: BLE001
                print(f"    ERROR: {e}")
            time.sleep(0.08)
        if not bars_by_sym:
            print("no klines")
            return 1
        last_t = max(b[-1]["t"] for b in bars_by_sym.values() if b)
        first_t = min(b[0]["t"] for b in bars_by_sym.values() if b)
        fwd = args.walk_forward * 86_400_000
        cut = last_t - fwd
        # Backtest is the older slice; forward is the latest held-out slice. Rules are not refit.
        bt_trades, bt_sym = _window_trades(bars_by_sym, first_t, cut, args.partition)
        fw_trades, fw_sym = _window_trades(bars_by_sym, cut, last_t + 1, args.partition)
        backtest = _pack("backtest", bt_trades, args.partition, args.equity, first_t, cut)
        forward = _pack("forward", fw_trades, args.partition, args.equity, cut, last_t + 1)
        backtest["per_symbol"] = bt_sym
        forward["per_symbol"] = fw_sym
        for block in (backtest, forward):
            block["summary"].pop("equity_curve", None)
        result = {
            "strategy": contract["strategy_id"],
            "data": f"binance USD-M public {DEFAULT_INTERVAL} klines (no synthetic fills, no random)",
            "method": {
                "entry": "rolling 15m% = close vs close 15x1m ago (live _rolling_pcts); latch on high-print >=5%; enter on close retrace 0.7-12 with live hot",
                "manage": "1m close mark; H/L prove touch; same-bar conflict = adverse-first",
                "universe": "fixed liquid set + live $10M floor (no today-top look-ahead ranking)",
                "costs": "taker fee + slip on each leg",
                "not": "no invented wick path, no random fills, no refit on forward window",
            },
            "costs": {"fee_rate": FEE_RATE, "slip_pct": SLIP_PCT},
            "desk": {
                "one_trade_at_a_time": True,
                "min_quote_vol_24h": MIN_QUOTE_VOL_24H,
                "entry_cooldown_ms": ENTRY_COOLDOWN_MS,
                "invalidation_cooldown_ms": INVALIDATION_COOLDOWN_MS,
                "episode_cooldown_ms": EPISODE_COOLDOWN_MS,
                "note": "WINDOW_MARK = still open at window end",
            },
            "symbol_vol_24h": {s: round(vol_map.get(s, 0.0), 2) for s in bars_by_sym},
            "rules": contract,
            "symbols": list(bars_by_sym.keys()),
            "days": args.days,
            "walk_forward_days": args.walk_forward,
            "backtest": {k: v for k, v in backtest.items() if k != "trades"},
            "forward": {k: v for k, v in forward.items() if k != "trades"},
            "backtest_trades": backtest["trades"],
            "forward_trades": forward["trades"],
        }
        Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print("\n=== BACKTEST (older held-in) ===")
        print(json.dumps(backtest["summary"], indent=2))
        print(json.dumps(backtest["per_reason_pnl"], indent=2))
        print("\n=== FORWARD 30d (latest held-out, no refit) ===")
        print(json.dumps(forward["summary"], indent=2))
        print(json.dumps(forward["per_reason_pnl"], indent=2))
        print(f"\nWrote {args.out}")
        return 0

    all_trades: list[Trade] = []
    per_symbol: dict[str, Any] = {}
    for sym in symbols:
        print(f"  {sym} ...", flush=True)
        try:
            bars = fetch_klines_days(sym, DEFAULT_INTERVAL, args.days)
            tr = simulate_symbol(sym, bars, args.partition)
            per_symbol[sym] = {
                "trades": len(tr),
                "pnl": round(sum(t.pnl for t in tr), 2),
                "bars": len(bars),
                "l1": sum(1 for t in tr if t.used_long1),
                "l2": sum(1 for t in tr if t.used_long2),
            }
            all_trades.extend(tr)
            print(
                f"    -> {len(tr)} trades, pnl={per_symbol[sym]['pnl']} "
                f"L1={per_symbol[sym]['l1']} L2={per_symbol[sym]['l2']}"
            )
        except Exception as e:  # noqa: BLE001
            per_symbol[sym] = {"error": str(e)}
            print(f"    ERROR: {e}")
        time.sleep(0.12)

    all_trades.sort(key=lambda t: t.entry_t)
    filtered: list[Trade] = []
    busy_until = 0
    for t in all_trades:
        if t.entry_t < busy_until:
            continue
        filtered.append(t)
        busy_until = t.exit_t
    skipped = len(all_trades) - len(filtered)
    summary = summarize(filtered, args.partition, args.equity)
    summary["skipped_overlap"] = skipped

    result = {
        "strategy": "short_first_v1",
        "rules": {
            "entry": f"15m ≥{GAIN_THRESHOLD_PCT}% + ≥{RETRACE_ENTRY_PCT}% retrace",
            "short_tp": f"-{SHORT_TP_PCT}%",
            "short_trail": f"MFE≥{SHORT_TRAIL_MFE}% then bounce {SHORT_TRAIL_PULLBACK_FLOOR_PCT}%",
            "long1": f"+{LONG1_ADVERSE_PCT}% → 10x; paired hold after hedge episode",
            "long2": f"+{LONG2_ADVERSE_PCT}% → 10x; paired hold after hedge episode",
            "rescue": f"long covers short + {HEDGE_RESCUE_BUFFER_PCT}% partition → flatten all",
            "invalidation": f">={PAIR_INVALIDATION_PCT}% adverse → flatten all",
            "smart_exit": f"{SMART_EXIT_PCT}% of partition (hedged only if short green)",
            "sizing": f"{PRIMARY_PARTITION_PCT}/{RECOVERY_PARTITION_PCT}/{RECOVERY_PARTITION_PCT} of ${args.partition}",
            "capital_locks": "no solo dump after +2%/L1; no L1/L2 at inv; $100 partition",
        },
        "symbols": symbols,
        "days": args.days,
        "per_symbol": per_symbol,
        "summary": summary,
        "trades": [
            {
                "symbol": t.symbol,
                "entry_t": t.entry_t,
                "exit_t": t.exit_t,
                "pnl": t.pnl,
                "reason": t.reason,
                "l1": t.used_long1,
                "l2": t.used_long2,
                "mae": round(t.max_adverse_pct, 2),
                "mfe": round(t.mfe_pct, 2),
            }
            for t in filtered
        ],
    }
    Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("\n=== short_first_v1 RESULT ===")
    print(json.dumps(summary, indent=2))
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
