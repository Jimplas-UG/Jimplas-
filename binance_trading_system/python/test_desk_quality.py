#!/usr/bin/env python3
"""Desk-quality gates — liquidity, episode cool-off, confirmed position cache.

Does NOT change frozen strategy knobs (gain/retrace/L1/L2/inv/TP/smart/partition).
"""
from __future__ import annotations

import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))

from binance_connector import BinanceConnector, BinanceConfig, PositionsUnavailable  # noqa: E402
from frozen_strategy import (  # noqa: E402
    GAIN_THRESHOLD_PCT,
    LONG1_ADVERSE_PCT,
    LOCKED_PARTITION_USD,
    PAIR_INVALIDATION_PCT,
    SHORT_TP_PCT,
)
from momentum_scanner import (  # noqa: E402
    ENTRY_COOLDOWN_MS,
    EPISODE_COOLDOWN_MS,
    INVALIDATION_COOLDOWN_MS,
    MIN_QUOTE_VOL_24H,
    CoinStrategy,
    MomentumScanner,
)


def test_strategy_knobs_untouched() -> None:
    assert abs(GAIN_THRESHOLD_PCT - 5.0) < 1e-9
    assert abs(LONG1_ADVERSE_PCT - 2.0) < 1e-9
    assert abs(PAIR_INVALIDATION_PCT - 6.5) < 1e-9
    assert abs(SHORT_TP_PCT - 2.5) < 1e-9
    assert abs(LOCKED_PARTITION_USD - 100.0) < 1e-9
    print("OK strategy knobs untouched")


def test_liquidity_rejects_thin_names() -> None:
    assert MIN_QUOTE_VOL_24H >= 1_000_000
    conn = SimpleNamespace(cfg=SimpleNamespace(paper=True, api_key=""), _connected=False)
    sc = MomentumScanner(conn, lambda: True)
    sc._volume_map_ready = True
    coin = CoinStrategy(symbol="JUNKUSDT")
    coin.quote_vol_24h = 500_000.0
    assert sc._liquidity_ok(coin) is False
    coin.quote_vol_24h = MIN_QUOTE_VOL_24H
    assert sc._liquidity_ok(coin) is True
    print("OK liquidity gate rejects thin 24h quote volume")


def test_invalidation_cooldown_longer_than_default() -> None:
    conn = SimpleNamespace(cfg=SimpleNamespace(paper=True, api_key=""), _connected=False)
    sc = MomentumScanner(conn, lambda: True)
    inv = sc._cooldown_ms_for_reason("INVALIDATION")
    tp = sc._cooldown_ms_for_reason("SHORT_TP")
    rescue = sc._cooldown_ms_for_reason("RESCUE")
    assert inv >= INVALIDATION_COOLDOWN_MS
    assert inv > tp
    assert rescue >= EPISODE_COOLDOWN_MS
    assert tp == ENTRY_COOLDOWN_MS or tp == max(0, ENTRY_COOLDOWN_MS)
    sc._arm_entry_cooldown("PORTALUSDT", "INVALIDATION")
    until = sc._entry_cooldown_until_ms["PORTALUSDT"]
    assert until > int(time.time() * 1000) + INVALIDATION_COOLDOWN_MS - 2000
    print("OK invalidation/episode cool-off longer than clean SHORT_TP")


def test_confirmed_positions_reuses_fresh_last_good() -> None:
    c = BinanceConnector(BinanceConfig(paper=False, testnet=True, api_key="k", api_secret="s"))
    c._last_good_positions = [
        {"symbol": "BTCUSDT", "volume": 1.0, "positionSide": "SHORT", "type": "SELL"}
    ]
    c._last_good_positions_ts = time.time()
    calls = {"n": 0}

    def boom(*_a, **_k):
        calls["n"] += 1
        raise RuntimeError("should not hit REST")

    c._request = boom  # type: ignore
    rows = c.confirmed_positions("BTCUSDT", max_age_s=2.0)
    assert len(rows) == 1
    assert calls["n"] == 0
    qty = c.exchange_short_qty("BTCUSDT", max_age_s=2.0)
    assert qty == 1.0
    assert calls["n"] == 0
    print("OK confirmed_positions / exchange_*_qty reuse fresh last_good")


def test_confirmed_positions_stale_force_unavailable() -> None:
    c = BinanceConnector(BinanceConfig(paper=False, testnet=True, api_key="k", api_secret="s"))
    c._last_good_positions = [
        {"symbol": "ETHUSDT", "volume": 2.0, "positionSide": "SHORT", "type": "SELL"}
    ]
    c._last_good_positions_ts = time.time() - 30.0
    c._rest_cool_until = time.monotonic() + 20.0
    c._rest_cool_reason = "429"
    raised = False
    try:
        c.confirmed_positions("ETHUSDT", max_age_s=1.5)
    except PositionsUnavailable:
        raised = True
    assert raised
    print("OK stale book + cool -> PositionsUnavailable (not flat)")


if __name__ == "__main__":
    test_strategy_knobs_untouched()
    test_liquidity_rejects_thin_names()
    test_invalidation_cooldown_longer_than_default()
    test_confirmed_positions_reuses_fresh_last_good()
    test_confirmed_positions_stale_force_unavailable()
    print("test_desk_quality: ALL OK")
