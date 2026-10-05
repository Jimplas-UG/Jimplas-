#!/usr/bin/env python3
import json
import os
import sys

sys.path.insert(0, "/opt/bilshenz/binance_trading_system/python")
os.chdir("/opt/bilshenz/binance_trading_system/python")

from binance_connector import BinanceConnector, config_from_env  # noqa: E402
from calendar_pnl import aggregate_income_days, day_key_from_ms  # noqa: E402
from trade_history import include_trade_time  # noqa: E402

c = BinanceConnector(config_from_env())
try:
    income = c._request(
        "GET",
        "/fapi/v1/income",
        {"incomeType": "REALIZED_PNL", "limit": 1000},
        signed=True,
    )
    print("income_rows", len(income or []))
    by = aggregate_income_days(income or [], include_trade_time=include_trade_time)
    print("income_days", len(by), "keys", sorted(by.keys())[-8:])
    for row in (income or [])[-5:]:
        ts = int(row.get("time") or 0)
        print(" sample", day_key_from_ms(ts), row.get("income"), row.get("symbol"))
except Exception as e:
    print("income_error", e)
print("cool_s", c.rest_cooling_left())
print("sticky_cal_days", len((getattr(c, "_last_good_calendar", None) or {}).get("days") or []))
print("sticky_deals", len(getattr(c, "_last_good_deals", []) or []))
