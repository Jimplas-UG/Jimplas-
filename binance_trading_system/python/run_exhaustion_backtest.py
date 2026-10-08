"""
Temporary exhaustion_v1 backtest — $100 partition, public Binance USDT-M data.

Does NOT alter live short_first_v1. Run:
  python run_exhaustion_backtest.py
  python run_exhaustion_backtest.py --days 45 --symbols BTCUSDT,ETHUSDT,SOLUSDT
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from exhaustion_research import (
    FEE_RATE,
    LONG1_ADVERSE_PCT,
    LONG1_LEV,
    LONG1_MARGIN_USD,
    LONG1_TP_PCT,
    LONG2_ADVERSE_PCT,
    LONG2_LEV,
    LONG2_MARGIN_USD,
    LONG2_STOP_PCT,
    LONG2_TP_PCT,
    PARTITION_USD,
    SHORT_LEV,
    SHORT_MARGIN_USD,
    SHORT_TP_PCT,
    SLIP_PCT,
    TIME_STOP_BARS_15M,
    TIME_STOP_MIN_MFE_ATR,
    ExhaustionBreakdown,
    adaptive_invalidation_pct,
    adaptive_retrace_pct,
    atr_pct_from_bars,
    band_for_score,
    classify_regime,
    compute_exhaustion,
    continuation_long_ok,
    sizing_snapshot,
    volume_zscore,
)

FAPI = "https://fapi.binance.com"
DATA = "https://fapi.binance.com"
CTX = ssl.create_default_context()


def _get(url: str, params: dict[str, Any] | None = None, retries: int = 4) -> Any:
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    last: Exception | None = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bilshenz-exhaustion-bt/1.0"})
            with urllib.request.urlopen(req, context=CTX, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(0.4 * (i + 1))
    raise RuntimeError(f"GET failed {url}: {last}")


def fetch_klines(symbol: str, interval: str, limit: int = 1500, end_ms: int | None = None) -> list[dict]:
    params: dict[str, Any] = {"symbol": symbol, "interval": interval, "limit": min(1500, limit)}
    if end_ms:
        params["endTime"] = int(end_ms)
    raw = _get(f"{FAPI}/fapi/v1/klines", params)
    out = []
    for k in raw or []:
        out.append(
            {
                "t": int(k[0]),
                "o": float(k[1]),
                "h": float(k[2]),
                "l": float(k[3]),
                "c": float(k[4]),
                "v": float(k[5]),
                "qv": float(k[7]),
                "tbv": float(k[9]),  # taker buy base
            }
        )
    return out


def fetch_klines_days(symbol: str, interval: str, days: int) -> list[dict]:
    """Paginate back `days` of history."""
    ms_per_bar = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "4h": 14_400_000, "1d": 86_400_000}[interval]
    need = int(days * 86_400_000 / ms_per_bar) + 5
    out: list[dict] = []
    end: int | None = None
    while len(out) < need:
        chunk = fetch_klines(symbol, interval, limit=1500, end_ms=end)
        if not chunk:
            break
        out = chunk + out
        end = chunk[0]["t"] - 1
        if len(chunk) < 1500:
            break
        time.sleep(0.12)
    # dedupe
    dedup = {b["t"]: b for b in out}
    bars = sorted(dedup.values(), key=lambda b: b["t"])
    cutoff = bars[-1]["t"] - days * 86_400_000 if bars else 0
    return [b for b in bars if b["t"] >= cutoff]


def fetch_funding(symbol: str, limit: int = 200) -> list[dict]:
    raw = _get(f"{FAPI}/fapi/v1/fundingRate", {"symbol": symbol, "limit": min(1000, limit)})
    return [{"t": int(x["fundingTime"]), "rate": float(x["fundingRate"]) * 100.0} for x in raw or []]


def fetch_oi_hist(symbol: str, period: str = "15m", limit: int = 500) -> list[dict]:
    try:
        raw = _get(
            f"{DATA}/futures/data/openInterestHist",
            {"symbol": symbol, "period": period, "limit": min(500, limit)},
        )
    except Exception:
        return []
    return [{"t": int(x["timestamp"]), "oi": float(x["sumOpenInterest"])} for x in raw or []]


def fetch_premium_klines(symbol: str, interval: str = "15m", limit: int = 500) -> list[dict]:
    try:
        raw = _get(
            f"{FAPI}/fapi/v1/premiumIndexKlines",
            {"symbol": symbol, "interval": interval, "limit": min(1500, limit)},
        )
    except Exception:
        return []
    return [{"t": int(k[0]), "c": float(k[4])} for k in raw or []]


def top_symbols(n: int = 12) -> list[str]:
    tickers = _get(f"{FAPI}/fapi/v1/ticker/24hr")
    rows = []
    skip_sub = ("USDC", "BUSD", "TUSD", "FDUSD", "BFUSD", "BTCDOM", "XAU", "XAG", "SOXL", "SLV", "TSLA", "MSTR", "COIN")
    for t in tickers or []:
        sym = str(t.get("symbol") or "")
        if not sym.endswith("USDT"):
            continue
        if any(x in sym for x in skip_sub):
            continue
        qv = float(t.get("quoteVolume") or 0)
        rows.append((qv, sym))
    rows.sort(reverse=True)
    out = []
    for _, s in rows:
        out.append(s)
        if len(out) >= n:
            break
    return out


def _feature_bundle(
    bars_15m: list[dict],
    i: int,
    *,
    btc_4h: list[dict],
    btc_1d: list[dict],
    bars_4h: list[dict],
    funding: list[dict],
    oi: list[dict],
    premium: list[dict],
    peak_taker: float | None = None,
):
    window = bars_15m[max(0, i - 48) : i + 1]
    closes = [b["c"] for b in window]
    highs = [b["h"] for b in window]
    lows = [b["l"] for b in window]
    vols = [b["v"] for b in window]
    atr = atr_pct_from_bars(highs, lows, closes, 14)
    look = bars_15m[max(0, i - 5) : i + 1]
    swing_low = min(b["l"] for b in look)
    px = bars_15m[i]["c"]
    ret = (px - swing_low) / swing_low * 100.0 if swing_low > 0 else 0.0
    # Also consider same-bar extension from open (live-like impulse).
    bar = bars_15m[i]
    bar_ext = (bar["h"] - bar["o"]) / bar["o"] * 100.0 if bar["o"] > 0 else 0.0
    ret = max(ret, bar_ext)
    vz = volume_zscore(vols, 48)
    tbv = sum(b["tbv"] for b in look)
    bv = sum(b["v"] for b in look) or 1.0
    taker_ratio = tbv / bv
    prev_look = bars_15m[max(0, i - 9) : i - 5] or look
    prev_ratio = sum(b["tbv"] for b in prev_look) / (sum(b["v"] for b in prev_look) or 1.0)
    t = bars_15m[i]["t"]

    def _ret(series: list[dict], cur: dict | None, n: int = 1) -> float:
        if not cur or not series:
            return 0.0
        idx = next((j for j, b in enumerate(series) if b["t"] == cur["t"]), -1)
        if idx < n:
            return 0.0
        a, b = series[idx - n]["c"], cur["c"]
        return (b - a) / a * 100.0 if a else 0.0

    btc4 = _asof(btc_4h, t)
    btc1 = _asof(btc_1d, t)
    c4 = _asof(bars_4h, t)
    regime = classify_regime(
        _ret(btc_4h, btc4, 1),
        _ret(btc_1d, btc1, 1),
        _ret(bars_4h, c4, 1) if c4 else None,
    )
    fund = _asof(funding, t)
    funding_pct = float(fund["rate"]) if fund else 0.0
    prem = _asof(premium, t)
    prem_prev = _asof(premium, t - 900_000)
    # premiumIndexKlines close is already a ratio (e.g. 0.0003); express in %
    basis = float(prem["c"]) * 100.0 if prem else 0.0
    basis_chg = (float(prem["c"]) - float(prem_prev["c"])) * 100.0 if prem and prem_prev else 0.0
    oi_chg = _oi_chg_pct(oi, t, 4)
    ex = compute_exhaustion(
        ret_15m_pct=ret,
        atr_pct=atr,
        volume_z=vz,
        taker_buy_ratio=taker_ratio,
        taker_ratio_delta=taker_ratio - prev_ratio,
        oi_chg_pct=oi_chg,
        funding_pct=funding_pct,
        basis_pct=basis,
        basis_chg_15m=basis_chg,
        regime=regime,
        book_score=None,
        peak_taker_ratio=peak_taker,
    )
    return {
        "atr": atr,
        "ret": ret,
        "vz": vz,
        "taker_ratio": taker_ratio,
        "oi_chg": oi_chg,
        "regime": regime,
        "ex": ex,
        "px": px,
        "funding_pct": funding_pct,
        "basis_pct": basis,
        "basis_chg": basis_chg,
    }


def _asof(series: list[dict], t: int, key: str = "t") -> dict | None:
    if not series:
        return None
    lo, hi = 0, len(series) - 1
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        if series[mid][key] <= t:
            best = series[mid]
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _oi_chg_pct(oi_series: list[dict], t: int, look_bars: int = 4) -> float:
    cur = _asof(oi_series, t)
    if not cur:
        return 0.0
    # find ~look_bars earlier
    target = t - look_bars * 900_000
    prev = _asof(oi_series, target)
    if not prev or prev["oi"] <= 0:
        return 0.0
    return (cur["oi"] - prev["oi"]) / prev["oi"] * 100.0


@dataclass
class Leg:
    side: str
    entry: float
    margin: float
    lev: int
    qty: float
    tp: float | None = None
    stop: float | None = None


@dataclass
class Trade:
    symbol: str
    entry_t: int
    entry_px: float
    exit_t: int = 0
    exit_px: float = 0.0
    reason: str = ""
    pnl: float = 0.0
    score: float = 0.0
    regime: str = ""
    exhaustion: dict = field(default_factory=dict)
    used_long1: bool = False
    used_long2: bool = False
    max_adverse_pct: float = 0.0
    mfe_pct: float = 0.0


def _pnl_leg(leg: Leg, px: float) -> float:
    if leg.side == "SELL":
        return (leg.entry - px) * leg.qty
    return (px - leg.entry) * leg.qty


def _fees(notional: float) -> float:
    return abs(notional) * (FEE_RATE + SLIP_PCT / 100.0)


def simulate_symbol(
    symbol: str,
    bars_15m: list[dict],
    bars_4h: list[dict],
    bars_1d: list[dict],
    btc_4h: list[dict],
    btc_1d: list[dict],
    funding: list[dict],
    oi: list[dict],
    premium: list[dict],
    partition: float,
) -> list[Trade]:
    scale = partition / PARTITION_USD
    short_m = SHORT_MARGIN_USD * scale
    l1_m = LONG1_MARGIN_USD * scale
    l2_m = LONG2_MARGIN_USD * scale

    trades: list[Trade] = []
    i = 60  # warm-up
    cooldown_until = 0

    while i < len(bars_15m) - 2:
        if bars_15m[i]["t"] < cooldown_until:
            i += 1
            continue

        feat0 = _feature_bundle(
            bars_15m,
            i,
            btc_4h=btc_4h,
            btc_1d=btc_1d,
            bars_4h=bars_4h,
            funding=funding,
            oi=oi,
            premium=premium,
        )
        if feat0["ret"] < 5.0:
            i += 1
            continue

        # Pump detected → pending. Track peak taker during impulse, then require fade.
        peak = bars_15m[i]["h"]
        peak_idx = i
        peak_taker = feat0["taker_ratio"]
        pump_ret = feat0["ret"]
        for j in range(i, min(i + 10, len(bars_15m))):
            if bars_15m[j]["h"] >= peak:
                peak = bars_15m[j]["h"]
                peak_idx = j
            fj = _feature_bundle(
                bars_15m,
                j,
                btc_4h=btc_4h,
                btc_1d=btc_1d,
                bars_4h=bars_4h,
                funding=funding,
                oi=oi,
                premium=premium,
            )
            peak_taker = max(peak_taker, fj["taker_ratio"])
            pump_ret = max(pump_ret, fj["ret"])

        atr = feat0["atr"]
        retrace_need = adaptive_retrace_pct(atr)
        entered = False
        entry_i = None
        ex = feat0["ex"]
        regime = feat0["regime"]

        for j in range(peak_idx, min(peak_idx + 16, len(bars_15m))):
            p = bars_15m[j]["c"]
            retrace = (peak - p) / peak * 100.0 if peak else 0.0
            fj = _feature_bundle(
                bars_15m,
                j,
                btc_4h=btc_4h,
                btc_1d=btc_1d,
                bars_4h=bars_4h,
                funding=funding,
                oi=oi,
                premium=premium,
                peak_taker=peak_taker,
            )
            ex = compute_exhaustion(
                ret_15m_pct=max(pump_ret, fj["ret"]),
                atr_pct=fj["atr"],
                volume_z=fj["vz"],
                taker_buy_ratio=fj["taker_ratio"],
                taker_ratio_delta=-max(0.0, peak_taker - fj["taker_ratio"]),
                oi_chg_pct=fj["oi_chg"],
                funding_pct=fj["funding_pct"],
                basis_pct=fj["basis_pct"],
                basis_chg_15m=fj["basis_chg"],
                regime=fj["regime"],
                peak_taker_ratio=peak_taker,
            )
            if retrace < retrace_need:
                continue
            # Soft taker fade: allow if buyers cooling OR absolute aggression already muted.
            fade = peak_taker - fj["taker_ratio"]
            if fj["taker_ratio"] > 0.58 and fade < 0.02:
                continue
            if not ex.passes_gate:
                continue
            entry_i = j
            entered = True
            regime = fj["regime"]
            atr = fj["atr"]
            break

        if not entered or entry_i is None:
            i = max(i + 1, peak_idx + 1)
            continue

        entry_px = bars_15m[entry_i]["c"] * (1.0 - SLIP_PCT / 100.0)
        short_qty = (short_m * SHORT_LEV) / entry_px
        short = Leg("SELL", entry_px, short_m, SHORT_LEV, short_qty, tp=entry_px * (1 - SHORT_TP_PCT / 100))
        long1: Leg | None = None
        long2: Leg | None = None
        inv_pct = adaptive_invalidation_pct(atr)
        inv_px = entry_px * (1 + inv_pct / 100.0)
        trough = entry_px
        peak_adv = 0.0
        fees = _fees(short_m * SHORT_LEV)
        trade = Trade(
            symbol=symbol,
            entry_t=bars_15m[entry_i]["t"],
            entry_px=entry_px,
            score=ex.total,
            regime=regime,
            exhaustion=asdict(ex),
        )

        exit_reason = ""
        exit_i = entry_i
        exit_px = entry_px
        for j in range(entry_i + 1, min(entry_i + 96, len(bars_15m))):  # ~24h max hold
            bar = bars_15m[j]
            px = bar["c"]
            hi, lo = bar["h"], bar["l"]
            adverse = (hi - entry_px) / entry_px * 100.0
            peak_adv = max(peak_adv, adverse)
            if px < trough:
                trough = px
            mfe = (entry_px - trough) / entry_px * 100.0
            trade.mfe_pct = max(trade.mfe_pct, mfe)
            trade.max_adverse_pct = peak_adv

            # TP check (use low for short)
            if lo <= short.tp:
                exit_px = short.tp
                exit_i = j
                exit_reason = "SHORT_TP"
                break

            # Invalidation (hard)
            if hi >= inv_px:
                exit_px = inv_px
                exit_i = j
                exit_reason = "INVALIDATION"
                break

            # Time stop ~30m with no meaningful MFE and still bullish
            if j - entry_i >= TIME_STOP_BARS_15M:
                if mfe < TIME_STOP_MIN_MFE_ATR * atr and adverse > 0:
                    exit_px = px
                    exit_i = j
                    exit_reason = "TIME_STOP"
                    break

            # Conditional hedges
            oi_now = _oi_chg_pct(oi, bar["t"], 4)
            vz_now = volume_zscore([b["v"] for b in bars_15m[max(0, j - 48) : j + 1]], 48)
            if long1 is None and continuation_long_ok(
                adverse_pct=adverse,
                threshold=LONG1_ADVERSE_PCT,
                volume_z=vz_now,
                oi_chg_pct=oi_now,
                regime=regime,
                stronger=False,
            ):
                l1_entry = entry_px * (1 + LONG1_ADVERSE_PCT / 100.0)
                l1_qty = (l1_m * LONG1_LEV) / l1_entry
                long1 = Leg(
                    "BUY",
                    l1_entry,
                    l1_m,
                    LONG1_LEV,
                    l1_qty,
                    tp=l1_entry * (1 + LONG1_TP_PCT / 100),
                )
                fees += _fees(l1_m * LONG1_LEV)
                trade.used_long1 = True

            if long2 is None and continuation_long_ok(
                adverse_pct=adverse,
                threshold=LONG2_ADVERSE_PCT,
                volume_z=vz_now,
                oi_chg_pct=oi_now,
                regime=regime,
                stronger=True,
            ):
                l2_entry = entry_px * (1 + LONG2_ADVERSE_PCT / 100.0)
                l2_qty = (l2_m * LONG2_LEV) / l2_entry
                long2 = Leg(
                    "BUY",
                    l2_entry,
                    l2_m,
                    LONG2_LEV,
                    l2_qty,
                    tp=l2_entry * (1 + LONG2_TP_PCT / 100),
                    stop=l2_entry * (1 - LONG2_STOP_PCT / 100),
                )
                fees += _fees(l2_m * LONG2_LEV)
                trade.used_long2 = True

            # Long exits
            if long1 and hi >= long1.tp:
                # close long1 only — keep short
                fees += _fees(long1.margin * long1.lev)
                # realize long1 pnl into fees offset via separate accounting at end
                # mark closed by storing realized in stop field hack — use list
                long1.stop = -999  # closed marker
                # realize immediately into a float bag
                if not hasattr(trade, "_realized"):
                    trade._realized = 0.0  # type: ignore[attr-defined]
                trade._realized += _pnl_leg(long1, long1.tp)  # type: ignore[attr-defined]
                long1 = None

            if long2:
                if long2.stop and lo <= long2.stop:
                    if not hasattr(trade, "_realized"):
                        trade._realized = 0.0  # type: ignore[attr-defined]
                    trade._realized += _pnl_leg(long2, long2.stop)  # type: ignore[attr-defined]
                    fees += _fees(long2.margin * long2.lev)
                    # circuit breaker — flatten short too
                    exit_px = px
                    exit_i = j
                    exit_reason = "LONG2_STOP_CIRCUIT"
                    long2 = None
                    break
                if long2.tp and hi >= long2.tp:
                    if not hasattr(trade, "_realized"):
                        trade._realized = 0.0  # type: ignore[attr-defined]
                    trade._realized += _pnl_leg(long2, long2.tp)  # type: ignore[attr-defined]
                    fees += _fees(long2.margin * long2.lev)
                    long2 = None

            # Long1 rescue: long1 profit >= short loss + 1% of partition
            if long1 and long1.stop != -999:
                sp = _pnl_leg(short, px)
                lp = _pnl_leg(long1, px)
                if lp >= (-sp) + 0.01 * partition and sp < 0:
                    exit_px = px
                    exit_i = j
                    exit_reason = "RESCUE_L1"
                    break
        else:
            # max hold
            exit_i = min(entry_i + 95, len(bars_15m) - 1)
            exit_px = bars_15m[exit_i]["c"]
            exit_reason = "MAX_HOLD"

        # Flatten remaining
        pnl = _pnl_leg(short, exit_px)
        if long1 and getattr(long1, "stop", None) != -999:
            pnl += _pnl_leg(long1, exit_px)
            fees += _fees(long1.margin * long1.lev)
        if long2:
            pnl += _pnl_leg(long2, exit_px)
            fees += _fees(long2.margin * long2.lev)
        pnl += float(getattr(trade, "_realized", 0.0))
        fees += _fees(short_m * SHORT_LEV)  # exit fee short
        pnl -= fees

        trade.exit_t = bars_15m[exit_i]["t"]
        trade.exit_px = exit_px
        trade.reason = exit_reason
        trade.pnl = round(pnl, 4)
        trades.append(trade)
        cooldown_until = trade.exit_t + 5 * 60_000
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
    by_regime: dict[str, list[float]] = {}
    for t in trades:
        by_regime.setdefault(t.regime, []).append(t.pnl)
    regime_stats = {
        k: {
            "n": len(v),
            "pnl": round(sum(v), 2),
            "avg": round(sum(v) / len(v), 2) if v else 0,
        }
        for k, v in by_regime.items()
    }
    gross = sum(t.pnl for t in trades)
    return {
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
        "sizing": sizing_snapshot(partition),
        "by_reason": by_reason,
        "by_regime": regime_stats,
        "equity_curve": curve,
        "hedge_rate_l1": round(sum(1 for t in trades if t.used_long1) / len(trades) * 100, 1) if trades else 0,
        "hedge_rate_l2": round(sum(1 for t in trades if t.used_long2) / len(trades) * 100, 1) if trades else 0,
    }


def _max_dd(curve: list[dict]) -> float:
    peak = curve[0]["equity"]
    dd = 0.0
    for p in curve:
        peak = max(peak, p["equity"])
        if peak > 0:
            dd = max(dd, (peak - p["equity"]) / peak * 100.0)
    return round(dd, 2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--symbols", type=str, default="")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--partition", type=float, default=100.0)
    ap.add_argument("--equity", type=float, default=100.0)
    ap.add_argument(
        "--threshold-offset",
        type=float,
        default=0.0,
        help="Subtract from regime thresholds (e.g. 8 softens 72→64 for sensitivity).",
    )
    ap.add_argument(
        "--out",
        type=str,
        default=str(Path(__file__).resolve().parent / "exhaustion_backtest_result.json"),
    )
    args = ap.parse_args()

    if args.threshold_offset:
        import exhaustion_research as er

        er.REGIME_THRESH = {
            k: max(50.0, v - abs(args.threshold_offset)) for k, v in er.REGIME_THRESH.items()
        }
        print(f"Regime thresholds softened by {args.threshold_offset}: {er.REGIME_THRESH}")

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("Fetching top liquid USDT-M symbols...")
        symbols = top_symbols(args.top)
    print(f"Symbols ({len(symbols)}): {', '.join(symbols)}")
    print(f"Window: {args.days}d | partition=${args.partition} | equity0=${args.equity}")
    print("Fetching BTC regime bars...")
    btc_4h = fetch_klines_days("BTCUSDT", "4h", args.days + 5)
    btc_1d = fetch_klines_days("BTCUSDT", "1d", args.days + 10)

    all_trades: list[Trade] = []
    per_symbol: dict[str, Any] = {}
    for sym in symbols:
        print(f"  {sym} ...", flush=True)
        try:
            bars = fetch_klines_days(sym, "15m", args.days)
            bars_4h = fetch_klines_days(sym, "4h", args.days + 5)
            bars_1d = fetch_klines_days(sym, "1d", args.days + 10)
            funding = fetch_funding(sym, 200)
            oi = fetch_oi_hist(sym, "15m", 500)
            premium = fetch_premium_klines(sym, "15m", 500)
            # OI hist limited to ~500 bars (~5d at 15m); still useful when present
            tr = simulate_symbol(
                sym, bars, bars_4h, bars_1d, btc_4h, btc_1d, funding, oi, premium, args.partition
            )
            per_symbol[sym] = {
                "trades": len(tr),
                "pnl": round(sum(t.pnl for t in tr), 2),
                "bars": len(bars),
            }
            all_trades.extend(tr)
            print(f"    -> {len(tr)} trades, pnl={per_symbol[sym]['pnl']}")
        except Exception as e:  # noqa: BLE001
            per_symbol[sym] = {"error": str(e)}
            print(f"    ERROR: {e}")
        time.sleep(0.15)

    all_trades.sort(key=lambda t: t.entry_t)
    # Enforce one-trade-at-a-time across symbols (matches live desk).
    filtered: list[Trade] = []
    busy_until = 0
    for t in all_trades:
        if t.entry_t < busy_until:
            continue
        filtered.append(t)
        busy_until = t.exit_t
    skipped_overlap = len(all_trades) - len(filtered)
    all_trades = filtered
    summary = summarize(all_trades, args.partition, args.equity)
    summary["skipped_overlap"] = skipped_overlap
    result = {
        "strategy": "exhaustion_v1_temp",
        "vs_live": "short_first_v1 unchanged; this is research-only",
        "changes_vs_live": [
            "no short trail",
            "exhaustion score + regime thresholds",
            "OI + taker + volume z + funding/basis gates",
            "ATR adaptive retrace + invalidation",
            "conditional Long1/Long2",
            "time stop ~30m",
            "Long2 stop circuit breaker",
            "partition accounting: max deployed margin $130 on $100 partition",
        ],
        "limitations": [
            "order-book weight redistributed when LOB history unavailable",
            "OI hist depth limited by Binance public endpoint (~500 pts)",
            "fees/slip approximate (taker 4bps + 5bps slip each side)",
            "one-symbol-at-a-time applied after per-symbol sims (chronological filter)",
            "thresholds not yet calibrated on large labeled history — treat as research",
        ],
        "symbols": symbols,
        "days": args.days,
        "per_symbol": per_symbol,
        "summary": summary,
        "trades": [
            {
                "symbol": t.symbol,
                "entry_t": t.entry_t,
                "exit_t": t.exit_t,
                "entry_px": t.entry_px,
                "exit_px": t.exit_px,
                "pnl": t.pnl,
                "reason": t.reason,
                "score": t.score,
                "regime": t.regime,
                "l1": t.used_long1,
                "l2": t.used_long2,
                "mae": t.max_adverse_pct,
                "mfe": t.mfe_pct,
            }
            for t in all_trades
        ],
    }
    Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print("\n=== RESULT ===")
    print(json.dumps(summary, indent=2))
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
