"""Trade history window — hide pre-baseline fills from calendar and recent deals."""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone


def trade_history_since_ms() -> int:
    """
    TRADE_HISTORY_SINCE env: YYYY-MM-DD (UTC) or epoch ms.
    Deals before this timestamp are omitted from app history views.
    """
    raw = os.environ.get("TRADE_HISTORY_SINCE", "").strip()
    if not raw:
        return 0
    if raw.isdigit():
        v = int(raw)
        return v if v > 1_000_000_000_000 else v * 1000
    try:
        dt = datetime.strptime(raw[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return 0


def trade_history_since_date() -> str | None:
    ms = trade_history_since_ms()
    if ms <= 0:
        return None
    return time.strftime("%Y-%m-%d", time.gmtime(ms / 1000))


def include_trade_time(ts_ms: int | float | None) -> bool:
    since = trade_history_since_ms()
    if since <= 0:
        return True
    return int(ts_ms or 0) >= since
