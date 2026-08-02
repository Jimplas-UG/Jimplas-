"""
Global one-pair isolation — only one symbol may hold positions at a time.

Enforced across scanner, manual orders, execution engine, and close flows.
Multiple legs (Short, Long1, Long2) on the same active symbol are allowed.

Close gates (close_all_pending / close_pending) MUST auto-expire when the exchange
is flat — a stuck gate permanently blocks the forward bot and scanner.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable

log = logging.getLogger("pair_isolation")

ExchangePositionsFn = Callable[[], list[dict[str, Any]]]
ScannerActiveFn = Callable[[], str | None]

# Safety TTL — after this, a close gate with no live volume is released.
CLOSE_GATE_TTL_MS = 120_000
# When the account is already flat, do not keep the gate longer than this.
CLOSE_GATE_FLAT_RELEASE_MS = 15_000


class PairIsolationGate:
    """Thread-safe gate for single active trading pair."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Ref-counted so nested begin/end (api_close → close_leg_manual) cannot clear early.
        self._close_refcount: dict[str, int] = {}
        self._close_started_ms: dict[str, int] = {}
        self._last_successful_order: dict[str, Any] = {}
        self._last_sync_ms: int = 0
        self._global_close_all: bool = False
        self._global_close_all_ms: int = 0

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
        # Release stale close gates before deciding — never leave trading dead forever.
        self.release_stale_close_gates(exchange_fn)
        with self._lock:
            if self._global_close_all:
                return False, "close_all_pending"
            if self._close_refcount.get(sym, 0) > 0:
                return False, "close_pending"
            active = self.active_symbol(scanner_fn, exchange_fn)
            if active and active != sym:
                return False, f"one_pair_active:{active}"
        return True, ""

    def is_close_pending(self, symbol: str) -> bool:
        with self._lock:
            if self._global_close_all:
                return True
            return self._close_refcount.get(symbol.upper(), 0) > 0

    def begin_close(self, symbol: str) -> None:
        sym = symbol.upper()
        now = int(time.time() * 1000)
        with self._lock:
            self._close_refcount[sym] = self._close_refcount.get(sym, 0) + 1
            self._close_started_ms.setdefault(sym, now)

    def end_close(self, symbol: str) -> None:
        sym = symbol.upper()
        with self._lock:
            n = self._close_refcount.get(sym, 0) - 1
            if n <= 0:
                self._close_refcount.pop(sym, None)
                self._close_started_ms.pop(sym, None)
            else:
                self._close_refcount[sym] = n

    def begin_close_all(self, symbols: list[str] | None = None) -> None:
        now = int(time.time() * 1000)
        with self._lock:
            self._global_close_all = True
            self._global_close_all_ms = now
            for s in symbols or []:
                sym = str(s).upper()
                if sym:
                    self._close_refcount[sym] = self._close_refcount.get(sym, 0) + 1
                    self._close_started_ms.setdefault(sym, now)

    def end_close_all(self, symbols: list[str] | None = None) -> None:
        with self._lock:
            self._global_close_all = False
            self._global_close_all_ms = 0
            for s in symbols or []:
                sym = str(s).upper()
                n = self._close_refcount.get(sym, 0) - 1
                if n <= 0:
                    self._close_refcount.pop(sym, None)
                    self._close_started_ms.pop(sym, None)
                else:
                    self._close_refcount[sym] = n

    def force_clear_close_gates(self, reason: str = "") -> dict[str, Any]:
        """Emergency release — use when exchange is flat but gates stuck."""
        with self._lock:
            pending = sorted(self._close_refcount.keys())
            was_all = self._global_close_all
            self._global_close_all = False
            self._global_close_all_ms = 0
            self._close_refcount.clear()
            self._close_started_ms.clear()
        if was_all or pending:
            log.warning(
                "pair_gate force-cleared close gates reason=%s close_all=%s pending=%s",
                reason or "manual",
                was_all,
                pending,
            )
        return {"ok": True, "cleared_close_all": was_all, "cleared_symbols": pending, "reason": reason}

    def release_stale_close_gates(
        self,
        exchange_fn: ExchangePositionsFn | None = None,
        *,
        ttl_ms: int = CLOSE_GATE_TTL_MS,
    ) -> dict[str, Any]:
        """
        Auto-heal stuck gates:
        - If exchange has no open volume, clear ALL close gates immediately.
        - If a per-symbol close refcount is older than TTL and that symbol is flat, drop it.
        - If close_all is older than TTL and account is flat, clear close_all.
        """
        now = int(time.time() * 1000)
        open_syms: set[str] = set()
        if exchange_fn is not None:
            try:
                for p in exchange_fn() or []:
                    s = str(p.get("symbol") or "").upper()
                    if s and float(p.get("volume") or 0) > 1e-12:
                        open_syms.add(s)
            except Exception as e:
                log.warning("release_stale_close_gates positions: %s", e)
                return {"ok": False, "error": str(e)}

        cleared_all = False
        cleared_syms: list[str] = []
        with self._lock:
            account_flat = exchange_fn is not None and not open_syms

            def _aged(started_ms: int, limit_ms: int) -> bool:
                return bool(started_ms) and now - started_ms >= limit_ms

            # Flat account: release gates that have been held past the flat-release window.
            if account_flat:
                flat_limit = min(ttl_ms, CLOSE_GATE_FLAT_RELEASE_MS)
                if self._global_close_all and _aged(self._global_close_all_ms, flat_limit):
                    self._global_close_all = False
                    self._global_close_all_ms = 0
                    cleared_all = True
                for sym in list(self._close_refcount.keys()):
                    if _aged(self._close_started_ms.get(sym, 0), flat_limit):
                        self._close_refcount.pop(sym, None)
                        self._close_started_ms.pop(sym, None)
                        cleared_syms.append(sym)
                # If close_all still set with zero refs and flat long enough, drop it.
                if (
                    self._global_close_all
                    and not self._close_refcount
                    and _aged(self._global_close_all_ms, flat_limit)
                ):
                    self._global_close_all = False
                    self._global_close_all_ms = 0
                    cleared_all = True
            else:
                # Account still has volume — only expire gates for symbols that are flat + aged.
                if (
                    self._global_close_all
                    and self._global_close_all_ms
                    and now - self._global_close_all_ms >= ttl_ms
                ):
                    # Keep close_all while ANY volume remains; only age-expire if somehow orphaned.
                    pass
                for sym in list(self._close_refcount.keys()):
                    if sym == "*":
                        continue
                    if sym in open_syms:
                        continue
                    started = self._close_started_ms.get(sym, 0)
                    if started and now - started >= ttl_ms:
                        self._close_refcount.pop(sym, None)
                        self._close_started_ms.pop(sym, None)
                        cleared_syms.append(sym)

        if cleared_all or cleared_syms:
            log.warning(
                "pair_gate released stale close gates close_all=%s symbols=%s open=%s",
                cleared_all,
                cleared_syms,
                sorted(open_syms),
            )
        return {
            "ok": True,
            "cleared_close_all": cleared_all,
            "cleared_symbols": cleared_syms,
            "open_symbols": sorted(open_syms),
        }

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
        # Heal before reporting so /health never shows a permanent false lock.
        self.release_stale_close_gates(exchange_fn)
        with self._lock:
            active = self.active_symbol(scanner_fn, exchange_fn)
            pending = sorted(s for s, n in self._close_refcount.items() if n > 0)
            return {
                "one_pair_mode": True,
                "active_symbol": active,
                "close_pending": pending,
                "close_all_pending": self._global_close_all,
                "close_all_pending_ms": self._global_close_all_ms or None,
                "last_successful_order": dict(self._last_successful_order) or None,
                "last_sync_ms": self._last_sync_ms or None,
            }


pair_gate = PairIsolationGate()
