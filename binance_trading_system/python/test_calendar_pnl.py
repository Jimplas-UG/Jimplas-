"""Calendar PnL aggregation accuracy tests."""
from __future__ import annotations

import os
import time

os.environ["TRADE_CALENDAR_TZ"] = "UTC"

from datetime import datetime, timezone  # noqa: E402

from calendar_pnl import (  # noqa: E402
    aggregate_deal_days,
    aggregate_income_days,
    day_key_from_ms,
    finalize_calendar_days,
    merge_calendar_day_buckets,
)


def _ms(y, m, d, hh=12):
    return int(time.mktime(time.strptime(f"{y}-{m:02d}-{d:02d} {hh}:00:00", "%Y-%m-%d %H:%M:%S"))) * 1000


def test_income_is_complete_source() -> None:
    # Simulate: userTrades only saw part of day; income has full closes.
    income = [
        {"time": _ms(2026, 7, 15), "income": "-50.25"},
        {"time": _ms(2026, 7, 15, 14), "income": "-165.24"},
        {"time": _ms(2026, 7, 15, 18), "income": "12.0"},
        # phantom leg dropped
        {"time": _ms(2026, 7, 14), "income": "-113805.2"},
    ]
    by = aggregate_income_days(income, include_trade_time=lambda t: True)
    assert "2026-07-15" in by
    assert abs(by["2026-07-15"]["pnl"] - (-50.25 - 165.24 + 12.0)) < 0.01
    assert by["2026-07-15"]["trades"] == 3
    assert "2026-07-14" not in by  # phantom capped out


def test_deals_skip_opens() -> None:
    deals = [
        {"time": _ms(2026, 7, 16), "profit": 0.0, "is_close": False},
        {"time": _ms(2026, 7, 16), "profit": -12.5, "is_close": True},
        {"time": _ms(2026, 7, 16), "profit": 3.0, "is_close": True},
    ]
    by = aggregate_deal_days(deals, include_trade_time=lambda t: True)
    assert by["2026-07-16"]["trades"] == 2
    assert abs(by["2026-07-16"]["pnl"] - (-9.5)) < 0.01


def test_merge_keeps_sticky_days() -> None:
    sticky = {"2026-09-23": {"pnl": -3.5, "trades": 4}}
    fresh = {"2026-09-24": {"pnl": 14.88, "trades": 6}}
    merged = merge_calendar_day_buckets(sticky, fresh, fresh_wins=True)
    assert set(merged.keys()) == {"2026-09-23", "2026-09-24"}


def test_utc_day_keeps_late_utc_close() -> None:
    """22:30 UTC stays on that Binance day, not the next Nairobi day."""
    ts = int(datetime(2026, 10, 20, 22, 30, tzinfo=timezone.utc).timestamp() * 1000)
    assert day_key_from_ms(ts) == "2026-10-20"


def test_income_rows_are_deduped() -> None:
    ts = _ms(2026, 10, 20)
    income = [
        {"time": ts, "income": "-10", "tranId": 7, "symbol": "DOODUSDT"},
        {"time": ts, "income": "-10", "tranId": 7, "symbol": "DOODUSDT"},
        {"time": ts, "income": "4", "tranId": 8, "symbol": "DOODUSDT"},
    ]
    by = aggregate_income_days(income, include_trade_time=lambda t: True)
    assert by["2026-10-20"]["trades"] == 2
    assert abs(by["2026-10-20"]["pnl"] - (-6)) < 0.01


def test_finalize_respects_since() -> None:
    by = {
        "2026-07-10": {"pnl": -10.0, "trades": 1},
        "2026-07-15": {"pnl": -5.0, "trades": 2},
    }
    days, total = finalize_calendar_days(by, days=400, since_date="2026-07-14")
    assert [d["date"] for d in days] == ["2026-07-15"]
    assert total == -5.0


if __name__ == "__main__":
    test_income_is_complete_source()
    test_deals_skip_opens()
    test_merge_keeps_sticky_days()
    test_utc_day_keeps_late_utc_close()
    test_income_rows_are_deduped()
    test_finalize_respects_since()
    print("test_calendar_pnl: ALL OK")

