"""
Dedicated Binance Futures execution engine — signal → validated → signed order.

Low-latency path: cached symbol filters, optional reference price (skip book ticker),
idempotent clientOrderId, structured error logs, timeout retry with exponential backoff.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("execution_engine")

RETRY_BACKOFF_MS = (100, 200, 400)
MAX_RETRIES = 3
CLIENT_ID_PREFIX = "BSV32"


def _env_truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


def _parse_binance_code(msg: str) -> int | None:
    m = re.search(r"(-?\d{4,5})", str(msg or ""))
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


@dataclass
class ExecutionSignal:
    symbol: str
    side: str
    quantity: float
    reference_price: float
    leverage: int = 5
    magic: int = 88001
    leg: str = "SHORT"
    sl: float | None = None
    tp: float | None = None
    signal_id: str = ""
    signal_ts_ms: int = 0
    margin_type: str = "ISOLATED"
    partition_usd: float = 0.0
    partition_pct: float = 0.0


@dataclass
class ExecutionResult:
    ok: bool
    symbol: str = ""
    side: str = ""
    quantity: float = 0.0
    fill_price: float = 0.0
    order_id: int | None = None
    client_order_id: str = ""
    latency_ms: float = 0.0
    signal_to_ack_ms: float | None = None
    error: str = ""
    http_code: int | None = None
    binance_code: int | None = None
    retry_count: int = 0
    retry_decision: str = "none"
    stage: str = "failed"
    tp_order_id: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "fill_price": self.fill_price,
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "latency_ms": self.latency_ms,
            "signal_to_ack_ms": self.signal_to_ack_ms,
            "error": self.error or None,
            "http_code": self.http_code,
            "binance_code": self.binance_code,
            "retry_count": self.retry_count,
            "retry_decision": self.retry_decision,
            "stage": self.stage,
            "tp_order_id": self.tp_order_id,
        }


@dataclass
class ExecutionEvent:
    ts: int
    symbol: str
    side: str
    quantity: float
    stage: str
    leg: str = ""
    order_id: int | None = None
    client_order_id: str = ""
    fill_price: float | None = None
    latency_ms: float | None = None
    error: str | None = None
    tp: float | None = None
    sl: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts,
            "symbol": self.symbol,
            "coin": self.symbol.replace("USDT", ""),
            "side": self.side,
            "quantity": self.quantity,
            "stage": self.stage,
            "leg": self.leg,
            "order_id": self.order_id,
            "client_order_id": self.client_order_id,
            "fill_price": self.fill_price,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "tp": self.tp,
            "sl": self.sl,
        }


class ExecutionEngine:
    """Validate risk + exchange filters, then place signed Binance Futures orders."""

    def __init__(
        self,
        connector: Any,
        *,
        session_ok: Callable[[], tuple[bool, str]] | None = None,
        max_open_trades: Callable[[], int] | None = None,
        open_trade_count: Callable[[], int] | None = None,
    ):
        self._connector = connector
        self._session_ok = session_ok
        self._max_open_trades = max_open_trades or (lambda: 1)
        self._open_trade_count = open_trade_count or (lambda: 0)
        self._events: deque[ExecutionEvent] = deque(maxlen=64)
        self._filled_client_ids: set[str] = set()
        self._inflight_client_ids: set[str] = set()
        self._last_error: str | None = None
        self._account_cache: tuple[float, float, float] = (0.0, 0.0, 0.0)
        self._account_cache_ts = 0.0
        self._isolation_check: Callable[[str], tuple[bool, str]] | None = None
        self._close_pending_check: Callable[[str], bool] | None = None
        self._latency_ring: deque[dict[str, Any]] = deque(maxlen=32)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def events(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._events]

    def latency_stats(self) -> list[dict[str, Any]]:
        return list(self._latency_ring)

    def set_isolation_hooks(
        self,
        *,
        can_open: Callable[[str], tuple[bool, str]] | None = None,
        close_pending: Callable[[str], bool] | None = None,
    ) -> None:
        self._isolation_check = can_open
        self._close_pending_check = close_pending

    def _emit(
        self,
        signal: ExecutionSignal,
        stage: str,
        *,
        order_id: int | None = None,
        client_order_id: str = "",
        fill_price: float | None = None,
        latency_ms: float | None = None,
        error: str | None = None,
    ) -> None:
        evt = ExecutionEvent(
            ts=int(time.time() * 1000),
            symbol=signal.symbol.upper(),
            side=signal.side.upper(),
            quantity=float(signal.quantity),
            stage=stage,
            leg=signal.leg,
            order_id=order_id,
            client_order_id=client_order_id,
            fill_price=fill_price,
            latency_ms=latency_ms,
            error=error,
            tp=signal.tp,
            sl=signal.sl,
        )
        self._events.appendleft(evt)

    def _log_failure(
        self,
        signal: ExecutionSignal,
        *,
        reason: str,
        http_code: int | None = None,
        binance_code: int | None = None,
        retry_decision: str = "none",
        quantity: float | None = None,
    ) -> None:
        qty = quantity if quantity is not None else signal.quantity
        self._last_error = f"{signal.symbol}: {reason}"
        log.error(
            "EXEC_FAIL ts=%s coin=%s side=%s qty=%s http=%s binance=%s reason=%s retry=%s",
            int(time.time() * 1000),
            signal.symbol,
            signal.side,
            qty,
            http_code,
            binance_code,
            reason,
            retry_decision,
        )

    def _client_order_id(self, signal: ExecutionSignal) -> str:
        base = signal.signal_id or f"{signal.symbol}_{signal.leg}_{signal.magic}"
        digest = hashlib.sha1(base.encode("utf-8")).hexdigest()[:10]
        cid = f"{CLIENT_ID_PREFIX}_{signal.leg}_{digest}"[:36]
        return cid

    def _validate_env(self) -> tuple[bool, str]:
        if os.environ.get("SCANNER_EXEC", "1").strip().lower() in ("0", "false", "off"):
            return False, "SCANNER_EXEC=0"
        if _env_truthy("FORWARD_DRY_RUN"):
            return False, "FORWARD_DRY_RUN"
        return True, ""

    def _validate_session(self) -> tuple[bool, str]:
        if self._session_ok:
            return self._session_ok()
        cfg = self._connector.cfg
        if getattr(cfg, "paper", False):
            return True, ""
        if not cfg.api_key:
            return False, "api_key_missing"
        if getattr(self._connector, "_connected", False):
            return True, ""
        return False, "binance_not_logged_in"

    def _validate_risk(self, signal: ExecutionSignal, info: dict[str, Any], price: float) -> str | None:
        from binance_connector import round_to_step

        qty = round_to_step(float(signal.quantity), float(info.get("stepSize") or 0.001))
        if qty <= 0:
            return "invalid_quantity"
        min_q = float(info.get("minQty") or 0.001)
        if qty < min_q:
            return f"quantity_below_min min={min_q}"
        notional = qty * price
        min_n = float(info.get("minNotional") or info.get("min_notional") or 5.0)
        if notional < min_n:
            return f"min_notional notional={notional:.4f} min={min_n}"
        max_open = int(self._max_open_trades())
        if signal.leg not in ("LONG1", "LONG2") and max_open > 0 and self._open_trade_count() >= max_open:
            return "max_open_trades"
        return None

    def _validate_short_first(self, signal: ExecutionSignal) -> str | None:
        """All trades start with short — block standalone BUY except recovery LONG1/LONG2."""
        side = signal.side.upper()
        leg = (signal.leg or "").upper()
        if side != "BUY":
            return None
        if leg not in ("LONG1", "LONG2"):
            return "buy_blocked_short_first_policy"
        sym = signal.symbol.upper()
        if getattr(self._connector.cfg, "paper", False):
            return None
        short_qty = 0.0
        if hasattr(self._connector, "exchange_short_qty"):
            short_qty = float(self._connector.exchange_short_qty(sym) or 0)
        if short_qty <= 1e-12:
            return "buy_blocked_no_exchange_short"
        if hasattr(self._connector, "ensure_hedge_mode"):
            ok, err = self._connector.ensure_hedge_mode()
            if not ok:
                return f"hedge_mode_required:{err}"
        return None

    def _validate_scanner_leg(self, signal: ExecutionSignal) -> str | None:
        """Scanner multi-leg strategy requires hedge mode on live accounts."""
        leg = (signal.leg or "").upper()
        if leg not in ("SHORT", "LONG1", "LONG2"):
            return None
        if getattr(self._connector.cfg, "paper", False):
            return None
        if hasattr(self._connector, "ensure_hedge_mode"):
            ok, err = self._connector.ensure_hedge_mode()
            if not ok:
                return f"hedge_mode_required:{err}"
        return None

    def _available_margin(self) -> float:
        now = time.time()
        if now - self._account_cache_ts < 2.0:
            return self._account_cache[0]
        cfg = self._connector.cfg
        if cfg.paper or not cfg.api_key:
            return 1e9
        try:
            acct = self._connector._request("GET", "/fapi/v2/account", signed=True)
            free = float(acct.get("availableBalance", 0))
            self._account_cache = (free, 0.0, now)
            self._account_cache_ts = now
            return free
        except Exception as e:
            log.warning("margin cache refresh: %s", e)
            return self._account_cache[0]

    def execute(self, signal: ExecutionSignal, *, manual: bool = False) -> ExecutionResult:
        t0 = time.perf_counter()
        sym = signal.symbol.upper()
        side = signal.side.upper()
        result = ExecutionResult(ok=False, symbol=sym, side=side, quantity=float(signal.quantity))

        if _env_truthy("FORWARD_DRY_RUN"):
            result.error = "FORWARD_DRY_RUN"
            result.stage = "blocked_env"
            self._log_failure(signal, reason=result.error, retry_decision="no_retry_env")
            self._emit(signal, "blocked", error=result.error)
            return result

        if not manual:
            ok_env, env_reason = self._validate_env()
            if not ok_env:
                result.error = env_reason
                result.stage = "blocked_env"
                self._log_failure(signal, reason=env_reason, retry_decision="no_retry_env")
                self._emit(signal, "blocked", error=env_reason)
                return result

        ok_sess, sess_reason = self._validate_session()
        if not ok_sess:
            result.error = sess_reason
            result.stage = "blocked_session"
            self._log_failure(signal, reason=sess_reason, retry_decision="no_retry_session")
            self._emit(signal, "blocked", error=sess_reason)
            return result

        if signal.reference_price <= 0:
            result.error = "invalid_reference_price"
            result.stage = "validation_failed"
            self._log_failure(signal, reason=result.error)
            self._emit(signal, "validation_failed", error=result.error)
            return result

        if self._close_pending_check and self._close_pending_check(sym):
            result.error = "close_pending"
            result.stage = "blocked_close_pending"
            self._log_failure(signal, reason=result.error, retry_decision="no_retry_close")
            self._emit(signal, "blocked", error=result.error)
            return result

        if self._isolation_check:
            ok_iso, iso_reason = self._isolation_check(sym)
            if not ok_iso:
                result.error = iso_reason
                result.stage = "blocked_isolation"
                self._log_failure(signal, reason=iso_reason, retry_decision="no_retry_isolation")
                self._emit(signal, "blocked", error=iso_reason)
                return result

        client_id = self._client_order_id(signal)
        result.client_order_id = client_id
        if client_id in self._filled_client_ids:
            result.error = "duplicate_order"
            result.stage = "duplicate"
            self._log_failure(signal, reason="duplicate_order", retry_decision="no_retry_duplicate")
            self._emit(signal, "duplicate", client_order_id=client_id, error=result.error)
            return result
        if client_id in self._inflight_client_ids:
            result.error = "order_in_flight"
            result.stage = "in_flight"
            self._emit(signal, "in_flight", client_order_id=client_id, error=result.error)
            return result

        try:
            info = self._connector.get_symbol_spec(sym)
        except Exception as e:
            result.error = f"invalid_symbol: {e}"
            result.stage = "validation_failed"
            self._log_failure(signal, reason=str(e))
            self._emit(signal, "validation_failed", error=result.error)
            return result

        risk_err = self._validate_risk(signal, info, signal.reference_price)
        if risk_err:
            result.error = risk_err
            result.stage = "risk_blocked"
            self._log_failure(signal, reason=risk_err, retry_decision="no_retry_risk")
            self._emit(signal, "risk_blocked", error=risk_err)
            return result

        leg_err = self._validate_scanner_leg(signal)
        if leg_err:
            result.error = leg_err
            result.stage = "blocked_leg_policy"
            self._log_failure(signal, reason=leg_err, retry_decision="no_retry_policy")
            self._emit(signal, "blocked", error=leg_err)
            return result

        short_err = self._validate_short_first(signal)
        if short_err:
            result.error = short_err
            result.stage = "blocked_short_first"
            self._log_failure(signal, reason=short_err, retry_decision="no_retry_policy")
            self._emit(signal, "blocked", error=short_err)
            return result

        free = self._available_margin()
        lev = max(int(signal.leverage), 1)
        notional = float(signal.quantity) * signal.reference_price
        if free < notional / lev * 1.05:
            result.error = f"insufficient_margin free={free:.2f}"
            result.stage = "risk_blocked"
            self._log_failure(signal, reason=result.error, retry_decision="retry_on_margin")
            self._emit(signal, "risk_blocked", error=result.error)
            return result

        self._emit(signal, "sending", client_order_id=client_id)
        self._inflight_client_ids.add(client_id)

        try:
            self._connector.prepare_symbol_cached(sym, signal.leverage, "ISOLATED")
            last_err: Exception | None = None
            for attempt in range(MAX_RETRIES + 1):
                try:
                    order_resp = self._connector.place_market_order(
                        sym,
                        side,
                        float(signal.quantity),
                        client_order_id=client_id,
                        reference_price=signal.reference_price,
                        leverage=signal.leverage,
                        leg=signal.leg,
                    )
                    result.retry_count = attempt
                    if not order_resp.get("ok"):
                        err = str(order_resp.get("error") or "order_failed")
                        code = order_resp.get("binance_code")
                        http = order_resp.get("http_code")
                        retryable = bool(order_resp.get("retryable"))
                        result.error = err
                        result.binance_code = code
                        result.http_code = http
                        if retryable and attempt < MAX_RETRIES:
                            wait = RETRY_BACKOFF_MS[min(attempt, len(RETRY_BACKOFF_MS) - 1)] / 1000.0
                            result.retry_decision = f"retry_{attempt + 1}_in_{wait}s"
                            log.warning(
                                "EXEC_RETRY coin=%s attempt=%s wait=%.3fs err=%s",
                                sym,
                                attempt + 1,
                                wait,
                                err,
                            )
                            time.sleep(wait)
                            continue
                        result.stage = "rejected"
                        result.retry_decision = "no_retry"
                        self._log_failure(
                            signal,
                            reason=err,
                            http_code=http,
                            binance_code=code,
                            retry_decision=result.retry_decision,
                        )
                        self._emit(signal, "rejected", client_order_id=client_id, error=err)
                        return result

                    fill = float(order_resp.get("fill_price") or signal.reference_price)
                    order_id = order_resp.get("order_id")
                    latency = round((time.perf_counter() - t0) * 1000, 1)
                    signal_to_ack = None
                    if signal.signal_ts_ms > 0:
                        signal_to_ack = round(time.time() * 1000 - signal.signal_ts_ms, 1)
                    result.ok = True
                    result.fill_price = fill
                    result.order_id = order_id
                    result.latency_ms = latency
                    result.signal_to_ack_ms = signal_to_ack
                    result.stage = "filled"
                    result.retry_decision = "success" if attempt else "none"
                    self._filled_client_ids.add(client_id)
                    self._last_error = None
                    self._latency_ring.appendleft(
                        {
                            "ts": int(time.time() * 1000),
                            "symbol": sym,
                            "leg": signal.leg,
                            "latency_ms": latency,
                            "signal_to_ack_ms": signal_to_ack,
                            "order_id": order_id,
                        }
                    )
                    self._emit(
                        signal,
                        "filled",
                        order_id=order_id,
                        client_order_id=client_id,
                        fill_price=fill,
                        latency_ms=latency,
                    )
                    log.info(
                        "EXEC_OK coin=%s side=%s qty=%s fill=%s order_id=%s latency_ms=%s signal_to_ack_ms=%s retries=%s",
                        sym,
                        side,
                        order_resp.get("quantity"),
                        fill,
                        order_id,
                        latency,
                        signal_to_ack,
                        attempt,
                    )

                    if signal.tp is not None:
                        try:
                            tp_resp = self._connector.place_tp_market(
                                sym,
                                side,
                                float(signal.tp),
                                float(order_resp.get("quantity") or signal.quantity),
                                client_id=f"{client_id}_TP",
                            )
                            if tp_resp.get("ok"):
                                result.tp_order_id = tp_resp.get("order_id")
                                self._emit(
                                    signal,
                                    "tp_placed",
                                    order_id=tp_resp.get("order_id"),
                                    client_order_id=f"{client_id}_TP",
                                )
                        except Exception as e:
                            log.warning("EXEC_TP_FAIL coin=%s err=%s", sym, e)
                            self._emit(signal, "tp_failed", error=str(e))

                    return result
                except Exception as e:
                    last_err = e
                    err = str(e)
                    code = _parse_binance_code(err)
                    retryable = "timeout" in err.lower() or "timed out" in err.lower() or "URLError" in err
                    if retryable and attempt < MAX_RETRIES:
                        wait = RETRY_BACKOFF_MS[min(attempt, len(RETRY_BACKOFF_MS) - 1)] / 1000.0
                        time.sleep(wait)
                        continue
                    break

            err = str(last_err) if last_err else "order_failed"
            result.error = err
            result.binance_code = _parse_binance_code(err)
            result.stage = "failed"
            result.latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            self._log_failure(signal, reason=err, binance_code=result.binance_code)
            self._emit(signal, "failed", client_order_id=client_id, error=err, latency_ms=result.latency_ms)
            return result
        finally:
            self._inflight_client_ids.discard(client_id)
