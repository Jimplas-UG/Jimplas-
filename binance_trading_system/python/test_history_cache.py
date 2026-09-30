"""Disk trade history cache round-trip."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from history_cache import load_history_cache, save_history_cache


def test_history_cache_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "cache.json"
        os.environ["TRADE_HISTORY_CACHE_FILE"] = str(path)
        save_history_cache(
            calendar={"ok": True, "days": [{"date": "2026-09-25", "pnl": 1.5, "trades": 2}]},
            deals=[{"order_id": "1", "time": 1, "profit": 1.5}],
            deal_symbols=["BTCUSDT"],
        )
        data = load_history_cache()
        assert data.get("v") == 1
        assert data["calendar"]["days"][0]["date"] == "2026-09-25"
        assert data["deals"][0]["order_id"] == "1"
        assert "BTCUSDT" in data["deal_symbols"]
        # merge write keeps prior calendar when only deals updated
        save_history_cache(deals=[{"order_id": "2", "time": 2, "profit": -1.0}])
        data2 = load_history_cache()
        assert data2["calendar"]["days"][0]["date"] == "2026-09-25"
        assert len(data2["deals"]) == 1
        assert data2["deals"][0]["order_id"] == "2"


if __name__ == "__main__":
    test_history_cache_roundtrip()
    print("test_history_cache: ALL OK")
