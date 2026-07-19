"""
Build accurate daily realized-PnL calendar from Binance income,
with phantom-leg filtering for desk partitions.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Callable
from zoneinfo import ZoneInfo


def max_calendar_leg_usd() -> float:
    return float(os.environ.get("TRADE_PNL_MAX_LEG", "5000"))


def max_calendar_day_usd() -> float:
    # Allow a busy day of many legs, still within partition realism.
    return float(os.environ.get("TRADE_PNL_MAX_DAY", "20000"))


def calendar_tz_name() -> str:
    """
    Day buckets for the Performance calendar.
    Default Africa/Nairobi (UTC+3) so 'today' matches East Africa desk hours.
    Override with TRADE_CALENDAR_TZ=UTC for strict Binance UTC days.
    """
    return (os.environ.get("TRADE_CALENDAR_TZ") or "Africa/Nairobi").strip() or "Africa/Nairobi"


def _tzinfo():
    name = calendar_tz_name()
    try:
        return ZoneInfo(name), name
    except Exception:
        # Fixed UTC+3 fallback if zoneinfo data missing on some hosts.
        return timezone(timedelta(hours=3)), "UTC+3"


def day_key_from_ms(ts_ms: int) -> str:
    tz, _ = _tzinfo()
    dt = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc).astimezone(tz)
    return dt.strftime("%Y-%m-%d")


def aggregate_income_days(
    income_rows: list[dict[str, Any]],
    *,
    include_trade_time: Callable[[int], bool],
    max_leg: float | None = None,
) -> dict[str, dict[str, float]]:
    """Day buckets from REALIZED_PNL income lines (desk-local calendar day)."""
    lim = max_leg if max_leg is not None else max_calendar_leg_usd()
    by_day: dict[str, dict[str, float]] = {}
    for row in income_rows or []:
        ts = int(row.get("time") or 0)
        if ts <= 0 or not include_trade_time(ts):
            continue
        try:
            pnl = float(row.get("income") or 0)
        except (TypeError, ValueError):
            continue
        if abs(pnl) < 1e-12:
            continue
        # Drop phantom single-leg hiccups (e.g. ~qty mistaken for USD).
        if abs(pnl) > lim:
            continue
        key = day_key_from_ms(ts)
        bucket = by_day.setdefault(key, {"pnl": 0.0, "trades": 0})
        bucket["pnl"] += pnl
        bucket["trades"] += 1
    return by_day


def aggregate_deal_days(
    deals: list[dict[str, Any]],
    *,
    include_trade_time: Callable[[int], bool],
    max_leg: float | None = None,
) -> dict[str, dict[str, float]]:
    """Fallback: closing fills with non-zero realized PnL (already sanitized)."""
    lim = max_leg if max_leg is not None else max_calendar_leg_usd()
    by_day: dict[str, dict[str, float]] = {}
    for d in deals or []:
        ts = int(d.get("time") or 0)
        if ts <= 0 or not include_trade_time(ts):
            continue
        try:
            pnl = float(d.get("profit") or d.get("realized_pnl") or 0)
        except (TypeError, ValueError):
            continue
        if abs(pnl) < 1e-12 or abs(pnl) > lim:
            continue
        # Prefer close fills only when flagged; otherwise allow any non-zero PnL.
        if d.get("is_close") is False:
            continue
        key = day_key_from_ms(ts)
        bucket = by_day.setdefault(key, {"pnl": 0.0, "trades": 0})
        bucket["pnl"] += pnl
        bucket["trades"] += 1
    return by_day


def finalize_calendar_days(
    by_day: dict[str, dict[str, float]],
    *,
    days: int,
    since_date: str | None,
    max_day: float | None = None,
) -> tuple[list[dict[str, Any]], float]:
    day_cap = max_day if max_day is not None else max_calendar_day_usd()
    _, tz_name = _tzinfo()
    days_out = [
        {"date": k, "pnl": round(v["pnl"], 2), "trades": int(v["trades"])}
        for k, v in sorted(by_day.items())
        if abs(v["pnl"]) <= day_cap
    ]
    # Cutoff date in the same calendar TZ.
    tz, _ = _tzinfo()
    now_local = datetime.now(tz)
    cutoff_dt = now_local - timedelta(days=max(1, int(days)))
    cutoff = cutoff_dt.strftime("%Y-%m-%d")
    if since_date and since_date > cutoff:
        cutoff = since_date
    days_out = [d for d in days_out if d["date"] >= cutoff]
    total = round(sum(d["pnl"] for d in days_out), 2)
    return days_out, total
