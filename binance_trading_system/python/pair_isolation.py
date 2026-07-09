"""
Global one-pair isolation — only one symbol may hold positions at a time.

Enforced across scanner, manual orders, execution engine, and close flows.
Multiple legs (Short, Long1, Long2) on the same active symbol are allowed.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

ExchangePositionsFn = Callable[[], list[dict[str, Any]]]
ScannerActiveFn = Callable[[], str | None]


class PairIsolationGate:
    """Thread-safe gate for single active trading pair."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._close_pending: set[str] = set()
        self._last_successful_order: dict[str, Any] = {}
        self._last_sync_ms: int = 0

    def active_symbol(
        self,
        scanner_fn: ScannerActiveFn,
        exchange_fn: ExchangePositionsFn,
    ) -> str | None:
        sym = scanner_fn()
        if sym:
            return sym.upper()
        for p in exchange_fn() or []:
            s = str(p.get("symbol") or "").upper()
            vol = float(p.get("volume") or 0)
            if s and vol > 1e-12:
                return s
        return None

    def has_active(self, scanner_fn: ScannerActiveFn, exchange_fn: ExchangePositionsFn) -> bool:
        return self.active_symbol(scanner_fn, exchange_fn) is not None

    def can_open(
        self,
        symbol: str,
        scanner_fn: ScannerActiveFn,
        exchange_fn: ExchangePositionsFn,
    ) -> tuple[bool, str]:
        sym = symbol.upper()
        with self._lock:
            if sym in self._close_pending:
                return False, "close_pending"
            active = self.active_symbol(scanner_fn, exchange_fn)
            if active and active != sym:
                return False, f"one_pair_active:{active}"
        return True, ""

    def is_close_pending(self, symbol: str) -> bool:
        with self._lock:
            return symbol.upper() in self._close_pending

    def begin_close(self, symbol: str) -> None:
        with self._lock:
            self._close_pending.add(symbol.upper())

    def end_close(self, symbol: str) -> None:
        with self._lock:
            self._close_pending.discard(symbol.upper())

    def record_order(
        self,
        *,
        symbol: str,
        side: str,
        order_id: int | None,
        latency_ms: float,
        source: str,
    ) -> None:
        with self._lock:
            self._last_successful_order = {
                "ts": int(time.time() * 1000),
                "symbol": symbol.upper(),
                "side": side.upper(),
                "order_id": order_id,
                "latency_ms": latency_ms,
                "source": source,
            }

    def touch_sync(self) -> None:
        with self._lock:
            self._last_sync_ms = int(time.time() * 1000)

    def status(
        self,
        scanner_fn: ScannerActiveFn | None = None,
        exchange_fn: ExchangePositionsFn | None = None,
    ) -> dict[str, Any]:
        scanner_fn = scanner_fn or (lambda: None)
        exchange_fn = exchange_fn or (lambda: [])
        with self._lock:
            active = self.active_symbol(scanner_fn, exchange_fn)
            return {
                "one_pair_mode": True,
                "active_symbol": active,
                "close_pending": sorted(self._close_pending),
                "last_successful_order": dict(self._last_successful_order) or None,
                "last_sync_ms": self._last_sync_ms or None,
            }


pair_gate = PairIsolationGate()
