#!/usr/bin/env python3
"""Integration test: qualified pending signal triggers ExecutionEngine short order."""
from __future__ import annotations

import os
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(__file__))

os.environ["SCANNER_EXEC"] = "1"
os.environ.pop("FORWARD_DRY_RUN", None)

from momentum_scanner import (  # noqa: E402
    MomentumScanner,
    STATUS_SHORT,
)


class ExecConnector:
    def __init__(self) -> None:
        self.cfg = SimpleNamespace(paper=True, api_key="test")
        self._connected = True
        self.orders: list[dict] = []

    def symbol_spec(self, symbol: str, pip_size: float = 0.01) -> dict:
        return {"stepSize": 0.001, "minQty": 0.001, "minNotional": 5.0}

    def get_symbol_spec(self, symbol: str) -> dict:
        return self.symbol_spec(symbol)

    def prepare_symbol_cached(self, symbol: str, leverage: int, margin_type: str = "ISOLATED") -> None:
        pass

    def place_market_order(self, symbol, side, quantity, **kwargs) -> dict:
        self.orders.append({"symbol": symbol, "side": side, "qty": quantity, **kwargs})
        return {"ok": True, "fill_price": 100.0, "quantity": quantity, "order_id": 42, "latency_ms": 35.0}

    def place_tp_market(self, *args, **kwargs) -> dict:
        return {"ok": True, "order_id": 99}


def _seed(sc: MomentumScanner, sym: str, base: float = 100.0) -> None:
    sc.load_symbols([sym])
    now = time.time()
    for m in range(16, 0, -1):
        sc.on_tick(sym, base, ts_ms=int((now - m * 60) * 1000))


def test_pending_triggers_short_order() -> None:
    conn = ExecConnector()
    sc = MomentumScanner(conn, lambda: True)
    sym = "TAGUSDT"
    sc.load_symbols([sym])
    sc.on_tick(sym, 1.0)
    coin = sc._coins[sym]
    from momentum_scanner import STATUS_PENDING

    coin.status = STATUS_PENDING
    coin.price = 1.25
    coin.best_pct = 6.0
    coin.qualifying_pct = 6.0
    coin.pct_15m = 6.0
    coin.retrace_pct = 0.8
    coin.highest_price = 1.26
    sc._try_open_short(coin)
    assert coin.status == STATUS_SHORT, f"expected SHORT got {coin.status}"
    assert len(conn.orders) >= 1, "order should be sent on qualification"
    assert conn.orders[0]["side"] == "SELL"
    events = sc._engine.events()
    assert any(e["stage"] == "filled" for e in events)
    print("OK pending -> auto short order")


if __name__ == "__main__":
    test_pending_triggers_short_order()
    print("test_exec_integration: OK")
