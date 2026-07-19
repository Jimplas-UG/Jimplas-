"""Calendar PnL aggregation accuracy tests."""
from __future__ import annotations

import os
import time

os.environ["TRADE_CALENDAR_TZ"] = "UTC"

from calendar_pnl import (  # noqa: E402
    aggregate_deal_days,
    aggregate_income_days,
    finalize_calendar_days,
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
    test_finalize_respects_since()
    print("test_calendar_pnl: ALL OK")
