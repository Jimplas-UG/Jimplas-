#!/usr/bin/env python3
"""Fixed leverage policy — primary long 5x, recovery shorts 10x."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from leverage_policy import (  # noqa: E402
    LONG1_LEVERAGE,
    LONG2_LEVERAGE,
    SHORT_LEVERAGE,
    apply_leverage_policy,
    exchange_leverage,
    required_leverage,
    sizing_leverage,
)


def test_constants() -> None:
    assert SHORT_LEVERAGE == 5
    assert LONG1_LEVERAGE == 10
    assert LONG2_LEVERAGE == 10
    print("OK constants 5/10/10")


def test_required_per_leg() -> None:
    assert required_leverage("SHORT") == 5
    assert required_leverage("LONG1", "BUY") == 5
    assert required_leverage("LONG1", "SELL") == 10
    assert required_leverage("LONG2", "SELL") == 10
    assert required_leverage("MANUAL", "SELL") == 5
    assert required_leverage("MANUAL", "BUY") is None
    print("OK required per leg")


def test_apply_overrides_wrong_request() -> None:
    assert apply_leverage_policy("SHORT", "SELL", 20) == 5
    assert apply_leverage_policy("LONG1", "BUY", 10) == 5
    assert apply_leverage_policy("LONG1", "SELL", 5) == 10
    assert apply_leverage_policy("LONG2", "SELL", 3) == 10
    print("OK apply overrides wrong leverage")


def test_exchange_leverage_always_5() -> None:
    assert exchange_leverage("SHORT") == 5
    assert exchange_leverage("LONG1") == 5
    assert exchange_leverage("LONG2") == 5
    print("OK exchange leverage always 5x on Binance API")


def test_sizing_differs_for_longs() -> None:
    assert sizing_leverage("SHORT") == 5
    assert sizing_leverage("LONG1", "BUY") == 5
    assert sizing_leverage("LONG1", "SELL") == 10
    assert sizing_leverage("LONG2", "SELL") == 10
    print("OK sizing leverage primary 5x / recovery 10x")


def test_policy_display_long_first() -> None:
    from leverage_policy import policy_display_leverage

    assert policy_display_leverage(side="BUY", position_side="LONG") == 5
    assert policy_display_leverage(side="SELL", position_side="SHORT") == 10
    assert policy_display_leverage(side="BUY") == 5
    assert policy_display_leverage(side="SELL") == 10
    print("OK display leverage long 5x / short 10x")


if __name__ == "__main__":
    test_constants()
    test_required_per_leg()
    test_apply_overrides_wrong_request()
    test_exchange_leverage_always_5()
    test_sizing_differs_for_longs()
    test_policy_display_long_first()
    print("test_leverage_policy: ALL OK")
