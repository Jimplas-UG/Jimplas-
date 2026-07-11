#!/usr/bin/env python3
from trade_history import include_trade_time, trade_history_since_date, trade_history_since_ms


def test_since_date() -> None:
    import os

    os.environ["TRADE_HISTORY_SINCE"] = "2026-07-11"
    assert trade_history_since_date() == "2026-07-11"
    since = trade_history_since_ms()
    assert include_trade_time(since) is True
    assert include_trade_time(since - 86400000) is False
    del os.environ["TRADE_HISTORY_SINCE"]
    assert trade_history_since_ms() == 0
    assert include_trade_time(1) is True
    print("OK trade history since")


def main() -> None:
    test_since_date()
    print("test_trade_history: ALL OK")


if __name__ == "__main__":
    main()
