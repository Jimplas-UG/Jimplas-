"""
Tick-by-tick multi-coin momentum scanner + retracement strategy (short-first).

Monitors 1m / 3m / 5m / 15m rolling % on every price tick (max study window 15m).
Entry: 15m move >= 5% gain, then >= 0.7% retrace from peak → Short (50% partition, 5x).
Recovery: +2% adverse from Short → Long 1 (40%, 10x); at +4% → Long 2 (40%, 10x).
Each recovery long requires a confirmed primary short, settle delay, and live adverse
(not peak-only latch). Long 1 / Long 2 each close on a 0.5% retrace from their own peak.
Short TP at 2.5% down; the short trail keeps a profitable-MFE floor so it never acts
as a hard stop. Recovery longs are never left without the primary short.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from execution_engine import ExecutionEngine, ExecutionSignal
from leverage_policy import LONG1_LEVERAGE, LONG2_LEVERAGE, SHORT_LEVERAGE
from pair_isolation import pair_gate
from strategy_guards import (
    clamp_exit_cost_pct,
    clamp_pullback_mfe_pct,
    clamp_pullback_pct,
    clamp_smart_exit_pct,
    is_toxic_legacy_sizing,
    sanitize_partitions,
)

log = logging.getLogger("momentum_scanner")

GAIN_THRESHOLD_PCT = float(os.environ.get("SCANNER_GAIN_PCT", "5.0"))
RETRACE_ENTRY_PCT = float(os.environ.get("SCANNER_RETRACE_PCT", "0.7"))
# Live 15m must still be hot at entry — blocks stale latched pumps (e.g. 15m already -16%).
MIN_LIVE_ENTRY_PCT = float(os.environ.get("SCANNER_MIN_LIVE_ENTRY_PCT", "2.0"))
# Reject end-of-pump entries: live 15m must keep at least this fraction of latched peak gain.
MIN_LIVE_VS_LATCH_FRAC = float(os.environ.get("SCANNER_MIN_LIVE_VS_LATCH", "0.45"))
# After flatten, block same-symbol re-entry so a dead pump cannot instantly re-grab the slot.
ENTRY_COOLDOWN_MS = int(os.environ.get("SCANNER_ENTRY_COOLDOWN_MS", "300000"))
# Do not short after the move is largely over (chasing a dump from peak).
MAX_RETRACE_ENTRY_PCT = float(os.environ.get("SCANNER_MAX_RETRACE_ENTRY_PCT", "12.0"))
SHORT_TP_PCT = float(os.environ.get("SCANNER_SHORT_TP_PCT", "2.5"))
# Adverse move for recovery longs — price rising ABOVE the primary short entry.
LONG1_ADVERSE_PCT = float(os.environ.get("SCANNER_LONG1_PCT", "2.0"))
LONG2_ADVERSE_PCT = float(os.environ.get("SCANNER_LONG2_PCT", "4.0"))
LONG_TP_PCT = float(os.environ.get("SCANNER_LONG_TP_PCT", "2.5"))
# Recovery longs close on a 0.5% retrace from their own peak — the original concept.
# Deliberately NOT clamped by strategy_guards: the 1.5% floor exists to stop a tight
# trail acting as a hard stop on the PRIMARY leg, which is the short.
LONG_HEDGE_PULLBACK_PCT = max(0.05, float(os.environ.get("SCANNER_LONG_PULLBACK_PCT", "0.5")))
LONG_BOTH_PULLBACK_PCT = LONG_HEDGE_PULLBACK_PCT
# Primary short trail — bounce off the trough, only after a profitable MFE.
SHORT_TRAIL_PULLBACK_PCT = clamp_pullback_pct(float(os.environ.get("SCANNER_SHORT_PULLBACK_PCT", "1.5")))
SHORT_TRAIL_MIN_MFE_PCT = clamp_pullback_mfe_pct(
    float(os.environ.get("SCANNER_SHORT_PULLBACK_MFE_PCT", "1.5"))
)
# Settle delay after the primary short fills before any recovery long may arm.
LONG_ENTRY_DELAY_MS = int(os.environ.get("SCANNER_LONG_DELAY_MS", "3000"))
# Smart exit floor — env 1.0 is forced up to 6.0; 0 disables.
SMART_EXIT_NET_PCT = clamp_smart_exit_pct(float(os.environ.get("SCANNER_SMART_EXIT_PCT", "6.0")))
EXIT_COST_BUFFER_PCT = clamp_exit_cost_pct(float(os.environ.get("SCANNER_EXIT_COST_PCT", "0.8")))
# Leverage fixed in leverage_policy.py — primary Short 5x, Long 1 / Long 2 10x sizing.
DEFAULT_PARTITION_USD = float(os.environ.get("SCANNER_PARTITION_USD", os.environ.get("SCANNER_RISK_USDT", "100")))
SHORT_PARTITION_PCT = float(os.environ.get("SCANNER_SHORT_PARTITION_PCT", "50"))
LONG1_PARTITION_PCT = float(os.environ.get("SCANNER_LONG1_PARTITION_PCT", "40"))
LONG2_PARTITION_PCT = float(os.environ.get("SCANNER_LONG2_PARTITION_PCT", "40"))
SHORT_PARTITION_PCT, LONG1_PARTITION_PCT, LONG2_PARTITION_PCT, _ = sanitize_partitions(
    SHORT_PARTITION_PCT, LONG1_PARTITION_PCT, LONG2_PARTITION_PCT
)
MAX_WATCHLIST = int(os.environ.get("SCANNER_MAX_WATCH", "80"))
ONE_TRADE_AT_A_TIME = os.environ.get("SCANNER_ONE_TRADE", "1").strip().lower() not in ("0", "false", "off")
SUBMIT_STALE_MS = int(os.environ.get("SCANNER_SUBMIT_STALE_MS", "90000"))
PENDING_STALE_MS = int(os.environ.get("SCANNER_PENDING_STALE_MS", "120000"))
PENDING_QUEUE_MS = int(os.environ.get("SCANNER_PENDING_QUEUE_MS", "1800000"))
SIGNALS_PER_TF = int(os.environ.get("SCANNER_SIGNALS_PER_TF", "5"))
TIMEFRAMES_MIN = (1, 3, 5, 15)
ENTRY_TIMEFRAME = os.environ.get("SCANNER_ENTRY_TF", "15m").strip().lower()
SIGNAL_WINDOW_SEC = {f"{m}m": m * 60 for m in TIMEFRAMES_MIN}
RISK_CONFIG_PATH = os.environ.get(
    "SCANNER_RISK_CONFIG_PATH", "/var/lib/bilshenz/scanner-risk.json"
)

MAGIC_SHORT = 88001
MAGIC_LONG1 = 88002
MAGIC_LONG2 = 88003

STATUS_SCANNING = "Scanning"
STATUS_WATCHING = "Watching"
STATUS_PENDING = "Pending"
STATUS_SHORT = "Short"
STATUS_LONG1 = "Long 1"
STATUS_LONG2 = "Long 2"
STATUS_CLOSED = "Closed"


def _env_truthy(name: str, default: str = "") -> bool:
    v = os.environ.get(name, default).strip().lower()
    return v in ("1", "true", "yes", "on")


def _exec_env_blocked() -> tuple[bool, str]:
    """Server env kill-switches — SCANNER_EXEC=0 or FORWARD_DRY_RUN=1."""
    if os.environ.get("SCANNER_EXEC", "1").strip().lower() in ("0", "false", "off"):
        return True, "SCANNER_EXEC=0"
    if _env_truthy("FORWARD_DRY_RUN"):
        return True, "FORWARD_DRY_RUN"
    return False, ""


@dataclass
class PricePoint:
    ts_ms: int
    price: float


@dataclass
class LegPosition:
    side: str
    entry: float
    qty: float
    leverage: int
    magic: int
    tp_price: float | None = None


@dataclass
class CoinStrategy:
    symbol: str
    price: float = 0.0
    pct_1m: float = 0.0
    pct_3m: float = 0.0
    pct_5m: float = 0.0
    pct_15m: float = 0.0
    pct_24h: float = 0.0
    quote_vol_24h: float = 0.0
    funding_rate: float | None = None
    best_pct: float = 0.0
    best_tf: str = ""
    qualifying_pct: float = 0.0
    status: str = STATUS_SCANNING
    highest_price: float | None = None
    retrace_pct: float = 0.0
    short: LegPosition | None = None
    long1: LegPosition | None = None
    long2: LegPosition | None = None
    long1_was_closed: bool = False
    long2_was_closed: bool = False
    short_was_closed: bool = False
    long1_peak_price: float | None = None
    long2_peak_price: float | None = None
    # Lowest price seen since the primary short filled — anchor for the short trail.
    short_trough_price: float | None = None
    long1_opened_ms: int = 0
    long2_opened_ms: int = 0
    short_opened_ms: int = 0
    short_adverse_peak_pct: float = 0.0
    independent_legs_mode: bool = False
    unrealized_pnl: float = 0.0
    last_update_ms: int = 0
    entry_signal_key: str = ""
    submitted_entry_signal_id: str = ""
    submitted_long1_signal_id: str = ""
    submitted_long2_signal_id: str = ""
    entry_submit_ms: int = 0
    long1_submit_ms: int = 0
    long2_submit_ms: int = 0
    _history: deque[PricePoint] = field(default_factory=lambda: deque(maxlen=2500))

    def active(self) -> bool:
        return self.status in (STATUS_WATCHING, STATUS_PENDING, STATUS_SHORT, STATUS_LONG1, STATUS_LONG2)


class MomentumScanner:
    """Runs on every mini-ticker tick across USDT-M perpetual symbols."""

    def __init__(
        self,
        connector: Any,
        get_testnet: Callable[[], bool],
        on_snapshot: Callable[[list[dict[str, Any]]], None] | None = None,
    ) -> None:
        self._connector = connector
        self._get_testnet = get_testnet
        self._on_snapshot = on_snapshot
        self._symbols_usdt: set[str] = set()
        self._coins: dict[str, CoinStrategy] = {}
        self._in_flight: set[str] = set()
        self._entry_cooldown_until_ms: dict[str, int] = {}
        self._lock = threading.RLock()
        self._last_broadcast = 0.0
        self._last_queue_block_log_ms = 0
        self._enabled = os.environ.get("SCANNER_ENABLED", "1").strip().lower() not in ("0", "false", "off")
        self._one_at_a_time = ONE_TRADE_AT_A_TIME
        self._trades_closed_today = 0
        self._trades_day_key = self._utc_day_key()
        self._partition_usd = DEFAULT_PARTITION_USD
        self._short_pct = SHORT_PARTITION_PCT
        self._long1_pct = LONG1_PARTITION_PCT
        self._long2_pct = LONG2_PARTITION_PCT
        self._risk_locked = False
        self._user_exec_halted = False
        self._load_persisted_risk()
        self._recent_signals: deque[dict[str, Any]] = deque(maxlen=48)
        self._last_exec_error: str | None = None
        self._session_ok_cache: tuple[float, tuple[bool, str]] | None = None
        self._tf_emit_times: dict[str, deque[float]] = {
            f"{m}m": deque(maxlen=SIGNALS_PER_TF + 2) for m in TIMEFRAMES_MIN
        }
        self._engine = ExecutionEngine(
            connector,
            session_ok=self._order_session_ok,
            max_open_trades=lambda: 1 if self._one_at_a_time else 999,
            # Count open symbols only — recovery legs on the same symbol are exempt in the engine.
            open_trade_count=lambda: 1 if self._global_active_symbol() else 0,
        )
        self._engine.set_isolation_hooks(
            can_open=lambda sym: pair_gate.can_open(
                sym, self._global_active_symbol, self._exchange_positions
            ),
            close_pending=pair_gate.is_close_pending,
        )
        self._last_exec_latency_ms: float | None = None
        self._last_reconcile_ms: int = 0

    @property
    def engine(self) -> ExecutionEngine:
        return self._engine

    def _exchange_positions(self) -> list[dict[str, Any]]:
        fn = getattr(self._connector, "positions", None)
        if not callable(fn):
            return []
        try:
            return fn() or []
        except Exception:
            return []

    def _exchange_short_leg(self, symbol: str) -> dict[str, Any] | None:
        """Live Binance short leg for symbol — the primary leg of every pair."""
        fn = getattr(self._connector, "exchange_short_qty", None)
        if callable(fn) and fn(symbol.upper()) > 1e-12:
            sym = symbol.upper()
            for p in self._exchange_positions():
                if str(p.get("symbol") or "").upper() != sym:
                    continue
                side = str(p.get("type") or p.get("side") or "").upper()
                pos_side = str(p.get("positionSide") or "").upper()
                if pos_side == "LONG":
                    continue
                if side == "SELL" or pos_side == "SHORT":
                    vol = float(p.get("volume") or 0)
                    if vol > 1e-12:
                        return p
        sym = symbol.upper()
        for p in self._exchange_positions():
            if str(p.get("symbol") or "").upper() != sym:
                continue
            side = str(p.get("type") or p.get("side") or "").upper()
            pos_side = str(p.get("positionSide") or "").upper()
            if pos_side == "LONG":
                continue
            if side == "SELL" or pos_side == "SHORT":
                vol = float(p.get("volume") or 0)
                if vol > 1e-12:
                    return p
        return None

    def _exchange_has_short(self, symbol: str) -> bool:
        if getattr(self._connector.cfg, "paper", False):
            coin = self._coins.get(symbol.upper())
            return bool(coin and coin.short)
        fn = getattr(self._connector, "exchange_short_qty", None)
        if callable(fn):
            return float(fn(symbol) or 0) > 1e-12
        return self._exchange_short_leg(symbol) is not None

    def _exchange_long_leg(self, symbol: str) -> dict[str, Any] | None:
        """Live Binance long leg for symbol — shared by recovery Long 1 / Long 2."""
        fn = getattr(self._connector, "exchange_long_qty", None)
        if callable(fn) and fn(symbol.upper()) > 1e-12:
            sym = symbol.upper()
            for p in self._exchange_positions():
                if str(p.get("symbol") or "").upper() != sym:
                    continue
                side = str(p.get("type") or p.get("side") or "").upper()
                pos_side = str(p.get("positionSide") or "").upper()
                if pos_side == "SHORT":
                    continue
                if side == "BUY" or pos_side == "LONG":
                    vol = float(p.get("volume") or 0)
                    if vol > 1e-12:
                        return p
        sym = symbol.upper()
        for p in self._exchange_positions():
            if str(p.get("symbol") or "").upper() != sym:
                continue
            side = str(p.get("type") or p.get("side") or "").upper()
            pos_side = str(p.get("positionSide") or "").upper()
            if pos_side == "SHORT":
                continue
            if side == "BUY" or pos_side == "LONG":
                vol = float(p.get("volume") or 0)
                if vol > 1e-12:
                    return p
        return None

    def _exchange_has_long(self, symbol: str) -> bool:
        if getattr(self._connector.cfg, "paper", False):
            coin = self._coins.get(symbol.upper())
            return bool(coin and (coin.long1 or coin.long2))
        fn = getattr(self._connector, "exchange_long_qty", None)
        if callable(fn):
            return float(fn(symbol) or 0) > 1e-12
        return self._exchange_long_leg(symbol) is not None

    def _exchange_has_orphan_long(self, symbol: str) -> bool:
        """Standalone long on exchange with no short — illegal under short-first policy."""
        if getattr(self._connector.cfg, "paper", False):
            return False
        long_fn = getattr(self._connector, "exchange_long_qty", None)
        short_fn = getattr(self._connector, "exchange_short_qty", None)
        if not callable(long_fn) or not callable(short_fn):
            return False
        return float(long_fn(symbol) or 0) > 1e-12 and float(short_fn(symbol) or 0) <= 1e-12

    def _sync_short_entry_from_exchange(self, coin: CoinStrategy) -> float:
        """Use exchange entry price for adverse % — avoids false triggers from bad fills."""
        short = coin.short
        if not short:
            return 0.0
        entry = float(short.entry or 0)
        if getattr(self._connector.cfg, "paper", False):
            return entry
        ex_leg = self._exchange_short_leg(coin.symbol)
        if ex_leg:
            ex_entry = float(ex_leg.get("price_open") or 0)
            if ex_entry > 0:
                entry = ex_entry
                short.entry = ex_entry
        return entry

    def _short_adverse_pct(self, coin: CoinStrategy) -> float:
        """Adverse move vs the primary short — price rising above the short entry."""
        if not coin.short:
            return 0.0
        entry = self._sync_short_entry_from_exchange(coin)
        if entry <= 0 or coin.price <= 0:
            return 0.0
        return ((coin.price - entry) / entry) * 100.0

    def _long1_entry_allowed(self, coin: CoinStrategy) -> bool:
        """Long 1 after primary short + settle delay when price is live ≥2% above short entry."""
        if not coin.short or coin.short_was_closed:
            return False
        if coin.long1 is not None or coin.long1_was_closed:
            return False
        if not self._exchange_has_short(coin.symbol):
            log.warning("scanner LONG1 blocked %s: no exchange short", coin.symbol)
            return False
        if not self._short_settle_elapsed(coin):
            return False
        live_adv = self._short_adverse_pct(coin)
        if live_adv > coin.short_adverse_peak_pct:
            coin.short_adverse_peak_pct = live_adv
        # Require live adverse — peak-only latched longs into fades and got scraped.
        if live_adv < LONG1_ADVERSE_PCT:
            return False
        return True

    def _long2_entry_allowed(self, coin: CoinStrategy) -> bool:
        """Long 2 at live ≥4% above the primary short entry.

        Prefer Long 1 still open. If Long 1 already TP'd / trailed off while the short is
        still underwater, still allow Long 2 so a continued pump is not left unhedged.
        """
        if not coin.short or coin.short_was_closed:
            return False
        if coin.long2 is not None or coin.long2_was_closed:
            return False
        if not self._exchange_has_short(coin.symbol):
            log.warning("scanner LONG2 blocked %s: no exchange short", coin.symbol)
            return False
        if coin.long1 is not None:
            if not self._exchange_has_long(coin.symbol):
                log.warning("scanner LONG2 blocked %s: no exchange long1", coin.symbol)
                return False
            if not self._long1_settle_elapsed(coin):
                return False
        elif not coin.long1_was_closed:
            # Long 1 never armed — wait for the +2% Long 1 first (ordered recovery).
            return False
        live_adv = self._short_adverse_pct(coin)
        if live_adv > coin.short_adverse_peak_pct:
            coin.short_adverse_peak_pct = live_adv
        if live_adv < LONG2_ADVERSE_PCT:
            return False
        return True

    def _recovery_still_eligible(self, coin: CoinStrategy) -> bool:
        """True while the short can still arm Long 1 and/or Long 2 on a pump."""
        if not coin.short or coin.short_was_closed:
            return False
        if coin.long1 is None and not coin.long1_was_closed:
            return True
        if coin.long2 is None and not coin.long2_was_closed:
            return True
        return False

    def _exit_cost_buffer_usd(self) -> float:
        return max(0.0, self._partition_usd * clamp_exit_cost_pct(EXIT_COST_BUFFER_PCT) / 100.0)

    def _effective_pullback_pct(self) -> float:
        """Primary short trail — floored so it can never become a hard stop."""
        return clamp_pullback_pct(SHORT_TRAIL_PULLBACK_PCT)

    def _effective_pullback_mfe_pct(self) -> float:
        return clamp_pullback_mfe_pct(SHORT_TRAIL_MIN_MFE_PCT)

    def _effective_long_pullback_pct(self) -> float:
        """Recovery Long 1 / Long 2 peak retrace — 0.5% by design, never floored to 1.5%."""
        return max(0.05, float(LONG_HEDGE_PULLBACK_PCT))

    def _effective_smart_exit_pct(self) -> float:
        return clamp_smart_exit_pct(SMART_EXIT_NET_PCT)

    def _short_pullback_allowed(self, coin: CoinStrategy, price: float) -> bool:
        """Trail the short only after profitable MFE — never act as a hard stop above entry."""
        if not coin.short or coin.short_trough_price is None:
            return False
        entry = float(coin.short.entry or 0)
        trough = float(coin.short_trough_price or 0)
        if entry <= 0 or trough <= 0 or price <= 0:
            return False
        # Must still be in profit vs entry (otherwise this is a stop, not a trail).
        if price >= entry:
            return False
        # Do not trail-scratch a naked short while Long 1 / Long 2 can still arm.
        if self._recovery_still_eligible(coin) and coin.long1 is None and coin.long2 is None:
            return False
        mfe_pct = ((entry - trough) / entry) * 100.0
        if mfe_pct < self._effective_pullback_mfe_pct():
            return False
        bounce_pct = ((price - trough) / trough) * 100.0
        if bounce_pct < self._effective_pullback_pct():
            return False
        # Keep the short open while recovery longs are still underwater.
        if coin.long1 or coin.long2:
            if coin.unrealized_pnl < self._exit_cost_buffer_usd():
                return False
        return True

    def _long_hedge_pullback_pct(self, peak: float, price: float) -> float:
        if peak <= 0 or price <= 0:
            return 0.0
        return ((peak - price) / peak) * 100.0

    def _short_settle_elapsed(self, coin: CoinStrategy) -> bool:
        if LONG_ENTRY_DELAY_MS <= 0:
            return True
        if not coin.short_opened_ms:
            return False
        return int(time.time() * 1000) - coin.short_opened_ms >= LONG_ENTRY_DELAY_MS

    def _long1_settle_elapsed(self, coin: CoinStrategy) -> bool:
        if LONG_ENTRY_DELAY_MS <= 0:
            return True
        if not coin.long1_opened_ms:
            return False
        return int(time.time() * 1000) - coin.long1_opened_ms >= LONG_ENTRY_DELAY_MS

    def _mark_long1_opened(self, coin: CoinStrategy, symbol: str) -> None:
        if not coin.long1_opened_ms:
            coin.long1_opened_ms = int(time.time() * 1000)
        sym = symbol.upper()
        if getattr(self._connector.cfg, "paper", False):
            return
        if self._exchange_has_long(sym):
            return
        try:
            self._connector.invalidate_positions_cache()
        except Exception:
            pass

    def _mark_long2_opened(self, coin: CoinStrategy) -> None:
        if not coin.long2_opened_ms:
            coin.long2_opened_ms = int(time.time() * 1000)

    def _mark_short_opened(self, coin: CoinStrategy, symbol: str) -> None:
        if not coin.short_opened_ms:
            coin.short_opened_ms = int(time.time() * 1000)
        sym = symbol.upper()
        if getattr(self._connector.cfg, "paper", False):
            return
        if self._exchange_has_short(sym):
            return
        try:
            self._connector.invalidate_positions_cache()
        except Exception:
            pass

    def _cancel_symbol_orders(self, symbol: str) -> None:
        if not hasattr(self._connector, "cancel_all_orders"):
            return
        try:
            self._connector.cancel_all_orders(symbol.upper())
        except Exception as e:
            log.warning("cancel orders %s: %s", symbol, e)

    def _place_leg_exchange_tp(self, coin: CoinStrategy, leg: LegPosition | None) -> None:
        if not leg or not leg.tp_price or leg.qty <= 0:
            return
        if getattr(self._connector.cfg, "paper", False):
            return
        if not hasattr(self._connector, "place_tp_market"):
            return
        try:
            self._connector.place_tp_market(
                coin.symbol,
                leg.side,
                float(leg.tp_price),
                float(leg.qty),
                client_id=f"scn_tp_{leg.magic}_{int(time.time() * 1000) % 1_000_000}",
            )
        except Exception as e:
            log.warning("re-place TP %s magic=%s: %s", coin.symbol, leg.magic, e)

    def _refresh_exchange_tps(self, coin: CoinStrategy) -> None:
        """After any partial close — wipe resting algos and re-arm remaining legs."""
        self._cancel_symbol_orders(coin.symbol)
        self._place_leg_exchange_tp(coin, coin.short)
        self._place_leg_exchange_tp(coin, coin.long1)
        self._place_leg_exchange_tp(coin, coin.long2)

    def _adopt_exchange_short(
        self,
        coin: CoinStrategy,
        symbol: str,
        fallback_qty: float,
        fallback_entry: float,
        tp: float,
    ) -> bool:
        """Recover primary short state when Binance filled but ACK was lost / duplicate blocked."""
        sym = symbol.upper()
        leg = self._exchange_short_leg(sym)
        if not leg:
            return False
        fill = float(leg.get("price_open") or fallback_entry or coin.price or 0)
        qty = float(leg.get("volume") or fallback_qty or 0)
        if fill <= 0 or qty <= 1e-12:
            return False
        coin.short = LegPosition("SELL", fill, qty, SHORT_LEVERAGE, MAGIC_SHORT, tp)
        coin.status = STATUS_SHORT
        coin.short_trough_price = fill
        coin.short_adverse_peak_pct = 0.0
        self._mark_short_opened(coin, sym)
        self._last_exec_error = None
        self._emit_signal(coin, "entered")
        log.info("scanner adopted exchange SHORT %s qty=%s @ %s", sym, qty, fill)
        return True

    def _adopt_exchange_long1(
        self,
        coin: CoinStrategy,
        symbol: str,
        fallback_qty: float,
        fallback_entry: float,
        tp: float,
    ) -> bool:
        """Adopt recovery Long 1 — only legal while the primary short exists."""
        sym = symbol.upper()
        if not coin.short and not self._exchange_has_short(sym):
            log.warning("scanner adopt LONG1 blocked %s: no exchange short", sym)
            return False
        leg = self._exchange_long_leg(sym)
        if not leg:
            return False
        fill = float(leg.get("price_open") or fallback_entry or coin.price or 0)
        qty = float(leg.get("volume") or fallback_qty or 0)
        if fill <= 0 or qty <= 1e-12:
            return False
        coin.long1 = LegPosition("BUY", fill, qty, LONG1_LEVERAGE, MAGIC_LONG1, tp)
        coin.status = STATUS_LONG1
        coin.long1_peak_price = fill
        self._mark_long1_opened(coin, sym)
        self._last_exec_error = None
        self._emit_signal(coin, "long1_entered")
        log.info("scanner adopted exchange LONG1 %s qty=%s @ %s", sym, qty, fill)
        return True

    def _recover_primary_short_entry(
        self,
        coin: CoinStrategy,
        symbol: str,
        fallback_qty: float,
        fallback_entry: float,
        tp: float,
    ) -> bool:
        """After fill/duplicate/in_flight — sync scanner state from exchange; never re-send."""
        sym = symbol.upper()
        try:
            self._connector.invalidate_positions_cache()
        except Exception:
            pass
        if self._adopt_exchange_short(coin, sym, fallback_qty, fallback_entry, tp):
            coin.submitted_entry_signal_id = coin.submitted_entry_signal_id or f"{sym}_SHORT_{coin.entry_signal_key}"
            return True
        if self._exchange_has_short(sym):
            return self._adopt_exchange_short(coin, sym, fallback_qty, fallback_entry, tp)
        return False

    def _recover_long1_entry(
        self,
        coin: CoinStrategy,
        symbol: str,
        fallback_qty: float,
        fallback_entry: float,
        tp: float,
    ) -> bool:
        sym = symbol.upper()
        try:
            self._connector.invalidate_positions_cache()
        except Exception:
            pass
        if self._adopt_exchange_long1(coin, sym, fallback_qty, fallback_entry, tp):
            coin.submitted_long1_signal_id = coin.submitted_long1_signal_id or f"{sym}_LONG1_{coin.entry_signal_key}"
            return True
        if self._exchange_has_long(sym):
            return self._adopt_exchange_long1(coin, sym, fallback_qty, fallback_entry, tp)
        return False

    def _adopt_exchange_long2(
        self,
        coin: CoinStrategy,
        symbol: str,
        fallback_qty: float,
        fallback_entry: float,
        tp: float,
    ) -> bool:
        """Adopt Long 2 from exchange long volume beyond Long 1 (best-effort)."""
        sym = symbol.upper()
        if not coin.short or not coin.long1:
            return False
        if coin.long2 is not None:
            return True
        leg = self._exchange_long_leg(sym)
        if not leg:
            return False
        fill = float(leg.get("price_open") or fallback_entry or coin.price or 0)
        qty = float(leg.get("volume") or 0)
        long1_qty = float(coin.long1.qty or 0)
        # If total long qty is materially larger than Long 1, treat the remainder as Long 2.
        extra = max(0.0, qty - long1_qty)
        use_qty = extra if extra > 1e-12 else float(fallback_qty or 0)
        if fill <= 0 or use_qty <= 1e-12:
            return False
        coin.long2 = LegPosition("BUY", fill, use_qty, LONG2_LEVERAGE, MAGIC_LONG2, tp)
        coin.long2_peak_price = fill
        coin.status = STATUS_LONG2
        self._mark_long2_opened(coin)
        self._last_exec_error = None
        self._emit_signal(coin, "long2_entered")
        log.info("scanner adopted exchange LONG2 %s qty=%s @ %s", sym, use_qty, fill)
        return True

    def _recover_long2_entry(
        self,
        coin: CoinStrategy,
        symbol: str,
        fallback_qty: float,
        fallback_entry: float,
        tp: float,
    ) -> bool:
        sym = symbol.upper()
        try:
            self._connector.invalidate_positions_cache()
        except Exception:
            pass
        if self._adopt_exchange_long2(coin, sym, fallback_qty, fallback_entry, tp):
            coin.submitted_long2_signal_id = coin.submitted_long2_signal_id or f"{sym}_LONG2_{coin.entry_signal_key}"
            return True
        return False

    def _clear_stale_submit(self, coin: CoinStrategy, which: str) -> bool:
        """Clear sticky submit only when stale and exchange confirms flat for that leg."""
        now = int(time.time() * 1000)
        if which == "entry":
            if not coin.submitted_entry_signal_id or coin.short:
                return False
            if coin.entry_submit_ms and now - coin.entry_submit_ms < SUBMIT_STALE_MS:
                return False
            if self._exchange_has_short(coin.symbol):
                return False
            coin.submitted_entry_signal_id = ""
            coin.entry_submit_ms = 0
            return True
        if which == "long1":
            if not coin.submitted_long1_signal_id or coin.long1:
                return False
            if coin.long1_submit_ms and now - coin.long1_submit_ms < SUBMIT_STALE_MS:
                return False
            if self._exchange_has_long(coin.symbol):
                return False
            coin.submitted_long1_signal_id = ""
            coin.long1_submit_ms = 0
            return True
        if which == "long2":
            if not coin.submitted_long2_signal_id or coin.long2:
                return False
            if coin.long2_submit_ms and now - coin.long2_submit_ms < SUBMIT_STALE_MS:
                return False
            coin.submitted_long2_signal_id = ""
            coin.long2_submit_ms = 0
            return True
        return False

    def set_exec_enabled(self, enabled: bool) -> None:
        """App emergency stop / resume — blocks new entries; closes still allowed."""
        halted = not enabled
        if self._user_exec_halted == halted:
            return
        self._user_exec_halted = halted
        self.invalidate_session_cache()
        self._persist_risk_config()
        can_exec, block = self._order_session_ok()
        log.info(
            "scanner set_exec_enabled(%s) user_halted=%s can_execute=%s block=%s",
            enabled,
            self._user_exec_halted,
            can_exec,
            block or "none",
        )

    def invalidate_session_cache(self) -> None:
        self._session_ok_cache = None

    def push_snapshot_now(self) -> None:
        """Force immediate WS/REST snapshot — call right after Binance login so exec shows armed."""
        self.invalidate_session_cache()
        self._last_broadcast = 0.0
        self._maybe_broadcast()

    def _session_connected(self) -> tuple[bool, str]:
        if getattr(self._connector.cfg, "paper", False):
            return True, ""
        if not self._connector.cfg.api_key:
            return False, "api_key_missing"
        if getattr(self._connector, "_connected", False):
            return True, ""
        # Keys configured but flag stale — one lightweight refresh (skip ping).
        try:
            snap = self._connector.status_snapshot(skip_ping=True)
            if snap.get("connected"):
                self._connector._connected = True
                return True, ""
            err = snap.get("error")
            if err:
                return False, str(err)[:120]
        except Exception as e:
            log.warning("session_connected status check: %s", e)
        return False, "binance_not_logged_in"

    def _order_session_ok(self) -> tuple[bool, str]:
        now = time.time()
        if self._session_ok_cache and now - self._session_ok_cache[0] < 0.05:
            return self._session_ok_cache[1]
        blocked, reason = _exec_env_blocked()
        if blocked:
            result = (False, reason)
        elif self._user_exec_halted:
            result = (False, "EMERGENCY_STOP")
        else:
            result = self._session_connected()
        self._session_ok_cache = (now, result)
        return result

    def _entry_qualify_pct(self, coin: CoinStrategy) -> float:
        """Entry uses 15m rolling % only — coin must jump >=5% on 15m before retrace entry."""
        if ENTRY_TIMEFRAME == "15m":
            return coin.pct_15m
        if ENTRY_TIMEFRAME == "5m":
            return coin.pct_5m
        if ENTRY_TIMEFRAME == "3m":
            return coin.pct_3m
        if ENTRY_TIMEFRAME == "1m":
            return coin.pct_1m
        return coin.pct_15m

    def _live_entry_ok(self, coin: CoinStrategy) -> bool:
        return self._entry_qualify_pct(coin) >= MIN_LIVE_ENTRY_PCT

    def _retrace_entry_ok(self, coin: CoinStrategy) -> bool:
        r = float(coin.retrace_pct or 0.0)
        return RETRACE_ENTRY_PCT <= r <= MAX_RETRACE_ENTRY_PCT

    def _pump_still_alive(self, coin: CoinStrategy) -> bool:
        """Block late entries where latched pump already died on the live 15m window."""
        peak = float(coin.qualifying_pct or 0.0)
        live = self._entry_qualify_pct(coin)
        if peak < GAIN_THRESHOLD_PCT:
            return False
        floor = max(MIN_LIVE_ENTRY_PCT, peak * max(0.2, min(0.9, MIN_LIVE_VS_LATCH_FRAC)))
        return live >= floor

    def _entry_signal_ok(self, coin: CoinStrategy) -> bool:
        latched = (coin.qualifying_pct or 0.0) >= GAIN_THRESHOLD_PCT
        return (
            latched
            and self._live_entry_ok(coin)
            and self._retrace_entry_ok(coin)
            and self._pump_still_alive(coin)
        )

    def _in_entry_cooldown(self, symbol: str) -> bool:
        until = int(self._entry_cooldown_until_ms.get(symbol.upper()) or 0)
        return until > int(time.time() * 1000)

    def _arm_entry_cooldown(self, symbol: str, reason: str = "") -> None:
        if ENTRY_COOLDOWN_MS <= 0:
            return
        sym = symbol.upper()
        until = int(time.time() * 1000) + ENTRY_COOLDOWN_MS
        self._entry_cooldown_until_ms[sym] = until
        log.info(
            "scanner entry cooldown %s for %ss reason=%s",
            sym,
            ENTRY_COOLDOWN_MS // 1000,
            reason or "flatten",
        )

    def reset_after_external_flatten(self, symbols: list[str] | None = None) -> dict[str, Any]:
        """Sync reset after desk/API close-all — stop instant re-entry on the same dead pump."""
        with self._lock:
            target = {s.upper() for s in (symbols or []) if s}
            reset: list[str] = []
            for sym, coin in list(self._coins.items()):
                if target and sym not in target:
                    continue
                if coin.long1 or coin.short or coin.long2 or coin.status in (
                    STATUS_PENDING,
                    STATUS_SHORT,
                    STATUS_LONG1,
                    STATUS_LONG2,
                ):
                    self._reset_coin_state(coin)
                    self._arm_entry_cooldown(sym, "external_flatten")
                    self._in_flight.discard(sym)
                    reset.append(sym)
            # Also cool down explicitly closed symbols even if scanner state was already empty.
            for sym in target:
                if sym not in reset:
                    self._arm_entry_cooldown(sym, "external_flatten")
            return {"ok": True, "reset": reset}

    def _demote_stale_pending(self, coin: CoinStrategy) -> None:
        """Drop pending queue rows whose pump died or dump already finished."""
        if coin.status != STATUS_PENDING or coin.short:
            return
        # Do not wipe sticky submit if exchange already has a short (ACK may be late).
        if coin.submitted_entry_signal_id and self._exchange_has_short(coin.symbol):
            return
        # While another pair is open, keep queued qualifiers — only drop if dump already finished.
        # Live < min is re-checked at fire time so we do not miss entries stuck behind one-trade.
        if self._has_open_strategy():
            if float(coin.retrace_pct or 0.0) > MAX_RETRACE_ENTRY_PCT:
                coin.status = STATUS_WATCHING
                coin.qualifying_pct = 0.0
                coin.entry_signal_key = ""
            return
        if not self._live_entry_ok(coin) or float(coin.retrace_pct or 0.0) > MAX_RETRACE_ENTRY_PCT:
            coin.status = STATUS_WATCHING
            coin.qualifying_pct = 0.0
            coin.entry_signal_key = ""
            # Keep sticky submit ids briefly so a late fill can still recover.
            if not coin.submitted_entry_signal_id:
                coin.submitted_entry_signal_id = ""
                coin.entry_submit_ms = 0
            coin.submitted_long1_signal_id = ""
            coin.submitted_long2_signal_id = ""
            coin.long1_submit_ms = 0
            coin.long2_submit_ms = 0

    def _apply_partition_guards(self, *, persist: bool = False) -> bool:
        """Clamp live risk knobs so out-of-policy sizing cannot stick (env/UI/JSON)."""
        short_pct, l1, l2, changed = sanitize_partitions(
            self._short_pct, self._long1_pct, self._long2_pct
        )
        if changed or is_toxic_legacy_sizing(self._short_pct, self._long1_pct, self._long2_pct):
            log.warning(
                "scanner risk sanitized short=%s%% long1=%s%% long2=%s%% (was %s/%s/%s)",
                short_pct,
                l1,
                l2,
                self._short_pct,
                self._long1_pct,
                self._long2_pct,
            )
            self._short_pct = short_pct
            self._long1_pct = l1
            self._long2_pct = l2
            if persist:
                self._persist_risk_config()
            return True
        self._short_pct = short_pct
        self._long1_pct = l1
        self._long2_pct = l2
        return changed

    def _persist_risk_config(self) -> None:
        # Never write toxic values to disk.
        self._short_pct, self._long1_pct, self._long2_pct, _ = sanitize_partitions(
            self._short_pct, self._long1_pct, self._long2_pct
        )
        payload = {
            "partition_usd": self._partition_usd,
            "short_pct": self._short_pct,
            "long1_pct": self._long1_pct,
            "long2_pct": self._long2_pct,
            "locked": self._risk_locked,
            "exec_halted": self._user_exec_halted,
        }
        try:
            path = RISK_CONFIG_PATH
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            tmp = f"{path}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp, path)
        except Exception as e:
            log.warning("persist risk config: %s", e)

    def _load_persisted_risk(self) -> None:
        try:
            if not os.path.isfile(RISK_CONFIG_PATH):
                self._apply_partition_guards(persist=False)
                return
            with open(RISK_CONFIG_PATH, encoding="utf-8") as fh:
                raw = json.load(fh)
            if float(raw.get("partition_usd") or 0) > 0:
                self._partition_usd = float(raw["partition_usd"])
            if raw.get("short_pct") is not None:
                self._short_pct = float(raw["short_pct"])
            if raw.get("long1_pct") is not None:
                self._long1_pct = float(raw["long1_pct"])
            if raw.get("long2_pct") is not None:
                self._long2_pct = float(raw["long2_pct"])
            self._risk_locked = bool(raw.get("locked"))
            if "exec_halted" in raw:
                self._user_exec_halted = bool(raw.get("exec_halted"))
            # Migrate out-of-policy locked sizing off disk on every boot.
            if self._apply_partition_guards(persist=True):
                self._risk_locked = False
                self._persist_risk_config()
            log.info(
                "scanner risk loaded partition=$%s short=%s%% l1=%s%% l2=%s%% locked=%s exec_halted=%s",
                self._partition_usd,
                self._short_pct,
                self._long1_pct,
                self._long2_pct,
                self._risk_locked,
                self._user_exec_halted,
            )
        except Exception as e:
            log.warning("load risk config: %s", e)
            self._apply_partition_guards(persist=False)

    def set_risk_config(
        self,
        partition_usd: float | None = None,
        short_pct: float | None = None,
        long1_pct: float | None = None,
        long2_pct: float | None = None,
    ) -> dict[str, Any]:
        if self._risk_locked:
            # Still migrate if locked out-of-policy config somehow remains.
            if is_toxic_legacy_sizing(self._short_pct, self._long1_pct, self._long2_pct):
                self._apply_partition_guards(persist=True)
                self._risk_locked = False
                self._persist_risk_config()
            else:
                changed = (
                    (partition_usd is not None and float(partition_usd) != self._partition_usd)
                    or (short_pct is not None and float(short_pct) != self._short_pct)
                    or (long1_pct is not None and float(long1_pct) != self._long1_pct)
                    or (long2_pct is not None and float(long2_pct) != self._long2_pct)
                )
                if changed:
                    return {
                        "ok": False,
                        "error": "partition_locked",
                        "partition_usd": self._partition_usd,
                        "short_pct": self._short_pct,
                        "long1_pct": self._long1_pct,
                        "long2_pct": self._long2_pct,
                        "locked": True,
                    }
        if partition_usd is not None and partition_usd > 0:
            self._partition_usd = float(partition_usd)
        if short_pct is not None:
            self._short_pct = max(1.0, min(100.0, float(short_pct)))
        if long1_pct is not None:
            self._long1_pct = max(1.0, min(100.0, float(long1_pct)))
        if long2_pct is not None:
            self._long2_pct = max(1.0, min(100.0, float(long2_pct)))
        self._apply_partition_guards(persist=False)
        if partition_usd is not None and partition_usd > 0:
            self._risk_locked = True
        self._persist_risk_config()
        log.info(
            "scanner risk partition=$%s short=%s%% long1=%s%% long2=%s%% locked=%s",
            self._partition_usd,
            self._short_pct,
            self._long1_pct,
            self._long2_pct,
            self._risk_locked,
        )
        return {
            "ok": True,
            "locked": self._risk_locked,
            "partition_usd": self._partition_usd,
            "short_pct": self._short_pct,
            "long1_pct": self._long1_pct,
            "long2_pct": self._long2_pct,
        }

    def close_strategy(self, symbol: str) -> dict[str, Any]:
        """Close full pair — short + all hedge longs on symbol."""
        sym = symbol.upper()
        coin = self._coins.get(sym)
        if not coin:
            return {"ok": False, "error": "unknown_symbol"}
        coin.independent_legs_mode = False
        if coin.short or coin.long1 or coin.long2:
            return self._close_all(coin, "MANUAL_PAIR")
        if coin.status == STATUS_PENDING:
            coin.status = STATUS_WATCHING
            return {"ok": True, "cancelled_pending": sym}
        return {"ok": False, "error": "nothing_to_close"}

    def close_leg_manual(
        self,
        symbol: str,
        position_side: str,
        volume: float | None = None,
    ) -> dict[str, Any]:
        """Close one hedge leg. Closing SHORT always flattens the full pair (no orphan longs)."""
        sym = symbol.upper()
        ps = position_side.upper()
        if ps not in ("SHORT", "LONG"):
            return {"ok": False, "error": "invalid_position_side"}
        coin = self._coins.get(sym)
        if ps == "SHORT" and coin and (coin.short or coin.long1 or coin.long2):
            coin.independent_legs_mode = False
            return self._close_all(coin, "MANUAL_SHORT_FLATTEN")
        pair_gate.begin_close(sym)
        t0 = time.perf_counter()
        try:
            if not hasattr(self._connector, "close_by_position_side"):
                return {"ok": False, "error": "close_by_position_side_unsupported"}
            r = self._connector.close_by_position_side(sym, ps, volume)
            if not r.get("ok"):
                return r
            if coin and ps == "LONG":
                # Closing recovery longs while the short remains is allowed.
                coin.independent_legs_mode = False
                coin.long1 = None
                coin.long2 = None
                coin.long1_peak_price = None
                coin.long2_peak_price = None
                coin.long1_was_closed = True
                coin.long2_was_closed = True
                coin.status = STATUS_SHORT if coin.short else STATUS_WATCHING
                self._refresh_exchange_tps(coin)
            self._connector.invalidate_positions_cache()
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            r["latency_ms"] = latency_ms
            r["position_side"] = ps
            r["closed"] = r.get("closed") or [r]
            pair_gate.record_order(
                symbol=sym,
                side=f"CLOSE_{ps}",
                order_id=r.get("order"),
                latency_ms=latency_ms,
                source="manual_leg",
            )
            log.info("manual close leg %s %s latency_ms=%s", sym, ps, latency_ms)
            return r
        finally:
            pair_gate.end_close(sym)

    def reset_symbol_if_flat(self, symbol: str) -> None:
        """Clear scanner legs when exchange position is gone."""
        sym = symbol.upper()
        open_syms = {str(p.get("symbol") or "").upper() for p in self._exchange_positions()}
        if sym in open_syms:
            return
        coin = self._coins.get(sym)
        if not coin:
            return
        if coin.short or coin.long1 or coin.long2 or coin.status in (
            STATUS_SHORT,
            STATUS_LONG1,
            STATUS_LONG2,
            STATUS_PENDING,
        ):
            self._reset_coin_state(coin)

    def _ensure_pair_coherence(self, coin: CoinStrategy) -> bool:
        """
        Active pair = open primary short on exchange. Long 1 / Long 2 are recovery hedges
        that only live while the short lives. If the short is gone, flatten the full
        symbol — never leave orphan longs.
        """
        sym = coin.symbol
        if getattr(self._connector.cfg, "paper", False):
            if not coin.short and (coin.long1 or coin.long2):
                self._close_all(coin, "PAIR_NO_SHORT")
                return False
            return coin.short is not None or coin.long1 is not None or coin.long2 is not None

        has_short = self._exchange_has_short(sym)
        has_long = self._exchange_has_long(sym)

        if coin.short and not has_short:
            log.info("scanner %s short closed on exchange — flattening full pair", sym)
            self._close_all(coin, "SHORT_GONE_EXCHANGE")
            return False

        # Never leave orphan longs without the primary short — even in independent_legs_mode.
        if not has_short and (coin.long1 or coin.long2 or has_long):
            log.warning("scanner %s recovery/orphan long without short — flattening full pair", sym)
            self._close_all(coin, "ORPHAN_RECOVERY")
            return False

        # Phantom Long 1 / Long 2 in memory after the shared LONG side was flattened.
        if has_short and not has_long and (coin.long1 or coin.long2):
            if coin.long1:
                log.info("scanner %s clearing phantom Long 1 — exchange LONG flat", sym)
                coin.long1 = None
                coin.long1_peak_price = None
                coin.long1_was_closed = True
            if coin.long2:
                log.info("scanner %s clearing phantom Long 2 — exchange LONG flat", sym)
                coin.long2 = None
                coin.long2_peak_price = None
                coin.long2_was_closed = True
            coin.status = STATUS_SHORT if coin.short else STATUS_WATCHING

        if not coin.short and not coin.long1 and not coin.long2:
            return False

        return True

    def reconcile_from_exchange(self) -> dict[str, Any]:
        """Sync scanner state to Binance — flatten orphan longs, reset flat symbols."""
        positions = self._exchange_positions()
        open_syms = {
            str(p.get("symbol") or "").upper()
            for p in positions
            if str(p.get("symbol") or "") and float(p.get("volume") or 0) > 1e-12
        }
        reset: list[str] = []
        # Exchange-first: any long without a short is illegal under short-first rules.
        for sym in sorted(open_syms):
            if self._exchange_has_long(sym) and not self._exchange_has_short(sym):
                log.warning("reconcile %s flatten orphan long without short", sym)
                try:
                    self._connector.close_position(sym, None)
                except Exception as e:
                    log.warning("reconcile flatten %s: %s", sym, e)
                coin = self._coins.get(sym)
                if coin:
                    self._reset_coin_state(coin)
                reset.append(sym)
                open_syms.discard(sym)
        for coin in list(self._coins.values()):
            sym = coin.symbol
            if sym in open_syms:
                if not self._exchange_has_short(sym) and (coin.long1 or coin.long2):
                    log.warning("reconcile %s flatten scanner recovery without short", sym)
                    try:
                        self._connector.close_position(sym, None)
                    except Exception as e:
                        log.warning("reconcile flatten %s: %s", sym, e)
                    self._reset_coin_state(coin)
                    reset.append(sym)
                continue
            if coin.short or coin.long1 or coin.long2 or coin.status in (
                STATUS_SHORT,
                STATUS_LONG1,
                STATUS_LONG2,
                STATUS_PENDING,
            ):
                self._reset_coin_state(coin)
                reset.append(coin.symbol)
        if reset:
            self._maybe_execute_best_pending()
        return {"ok": True, "open_symbols": sorted(open_syms), "reset_symbols": reset}

    def _reset_coin_state(self, coin: CoinStrategy) -> None:
        coin.short = None
        coin.long1 = None
        coin.long2 = None
        coin.long1_was_closed = False
        coin.long2_was_closed = False
        coin.short_was_closed = False
        coin.long1_peak_price = None
        coin.long2_peak_price = None
        coin.short_trough_price = None
        coin.long1_opened_ms = 0
        coin.long2_opened_ms = 0
        coin.short_opened_ms = 0
        coin.short_adverse_peak_pct = 0.0
        coin.independent_legs_mode = False
        coin.status = STATUS_CLOSED
        coin.highest_price = None
        coin.qualifying_pct = 0.0
        coin.entry_signal_key = ""
        coin.submitted_entry_signal_id = ""
        coin.submitted_long1_signal_id = ""
        coin.submitted_long2_signal_id = ""
        coin.entry_submit_ms = 0
        coin.long1_submit_ms = 0
        coin.long2_submit_ms = 0
        coin.unrealized_pnl = 0.0
        coin.retrace_pct = 0.0
        self._in_flight.discard(coin.symbol)

    def _can_emit_tf_signal(self, tf: str) -> bool:
        window = SIGNAL_WINDOW_SEC.get(tf, 180)
        now = time.time()
        q = self._tf_emit_times.setdefault(tf, deque(maxlen=SIGNALS_PER_TF + 2))
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= SIGNALS_PER_TF:
            return False
        q.append(now)
        return True

    def _emit_signal(self, coin: CoinStrategy, event: str) -> None:
        tf = coin.best_tf or "15m"
        if event == "watch" and not self._can_emit_tf_signal(tf):
            return
        # Always surface pending/entry events — do not throttle execution-critical signals.
        sig = {
            "id": f"{coin.symbol}-{event}-{int(time.time() * 1000)}",
            "symbol": coin.symbol,
            "coin": coin.symbol.replace("USDT", ""),
            "event": event,
            "timeframe": tf,
            "pctGain": round(coin.best_pct, 2),
            "retracePct": round(coin.retrace_pct, 2),
            "price": round(coin.price, 8),
            "status": coin.status,
            "ts": int(time.time() * 1000),
        }
        self._recent_signals.appendleft(sig)

    def trade_blocks(self) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for coin in self._coins.values():
            if coin.status not in (STATUS_PENDING, STATUS_SHORT, STATUS_LONG1, STATUS_LONG2):
                continue
            legs = []
            if coin.short:
                legs.append({"leg": "Short", "side": "SELL", "entry": coin.short.entry, "qty": coin.short.qty})
            if coin.long1:
                legs.append({"leg": "Long 1", "side": "BUY", "entry": coin.long1.entry, "qty": coin.long1.qty})
            if coin.long2:
                legs.append(
                    {
                        "leg": "Long 2",
                        "side": coin.long2.side,
                        "entry": coin.long2.entry,
                        "qty": coin.long2.qty,
                    }
                )
            blocks.append(
                {
                    "symbol": coin.symbol,
                    "coin": coin.symbol.replace("USDT", ""),
                    "status": coin.status,
                    "price": round(coin.price, 8),
                    "pctGain": round(coin.best_pct, 2),
                    "retracePct": round(coin.retrace_pct, 2),
                    "timeframe": coin.best_tf,
                    "unrealizedPnl": round(coin.unrealized_pnl, 2),
                    "legs": legs,
                    "canClose": True,
                }
            )
        blocks.sort(
            key=lambda b: (
                0 if b["status"] in (STATUS_SHORT, STATUS_LONG1, STATUS_LONG2) else 1,
                -b["pctGain"],
            )
        )
        return blocks

    def full_snapshot(self) -> dict[str, Any]:
        return {
            "rows": self.snapshot_rows(),
            "scanner": self.status(),
            "signals": list(self._recent_signals),
            "blocks": self.trade_blocks(),
            "execution_events": self._engine.events()[:16],
            "ts": int(time.time() * 1000),
        }

    @staticmethod
    def _utc_day_key() -> str:
        import datetime as _dt

        return _dt.datetime.utcnow().strftime("%Y-%m-%d")

    def _bump_trades_closed(self) -> None:
        day = self._utc_day_key()
        if day != self._trades_day_key:
            self._trades_day_key = day
            self._trades_closed_today = 0
        self._trades_closed_today += 1

    def _global_active_symbol(self) -> str | None:
        """Symbol with open scanner legs OR any live exchange position (blocks stacking)."""
        for coin in self._coins.values():
            if coin.short or coin.long1 or coin.long2:
                return coin.symbol
            if coin.status in (STATUS_SHORT, STATUS_LONG1, STATUS_LONG2):
                return coin.symbol
        for p in self._exchange_positions():
            sym = str(p.get("symbol") or "").upper()
            vol = float(p.get("volume") or 0)
            if sym and vol > 1e-12:
                return sym
        return None

    def _has_open_strategy(self) -> bool:
        return self._global_active_symbol() is not None

    def _entry_score(self, coin: CoinStrategy) -> float:
        """Rank pending candidates — highest momentum + confirmed retrace wins."""
        tf_bonus = {"15m": 1.5, "5m": 1.0, "3m": 0.75, "1m": 0.5}.get(coin.best_tf, 0.0)
        return coin.best_pct * 10.0 + coin.retrace_pct * 2.0 + tf_bonus

    def _pending_candidates(self) -> list[CoinStrategy]:
        now_ms = int(time.time() * 1000)
        out: list[CoinStrategy] = []
        for coin in self._coins.values():
            if coin.symbol in self._in_flight:
                continue
            if coin.short:
                continue
            if coin.status != STATUS_PENDING:
                continue
            self._demote_stale_pending(coin)
            if coin.status != STATUS_PENDING:
                continue
            if not self._retrace_entry_ok(coin):
                continue
            if self._in_entry_cooldown(coin.symbol):
                continue
            gain = max(coin.qualifying_pct or 0.0, self._entry_qualify_pct(coin))
            if gain < GAIN_THRESHOLD_PCT:
                continue
            if not self._live_entry_ok(coin) or not self._pump_still_alive(coin):
                continue
            stale_ms = PENDING_QUEUE_MS if self._has_open_strategy() else PENDING_STALE_MS
            if stale_ms > 0 and coin.last_update_ms and now_ms - coin.last_update_ms > stale_ms:
                coin.status = STATUS_WATCHING
                continue
            out.append(coin)
        out.sort(key=self._entry_score, reverse=True)
        return out

    def _maybe_execute_best_pending(self) -> None:
        """One open strategy at a time — best qualifier enters; rest stay queued until close."""
        ok, reason = self._order_session_ok()
        if not ok:
            if reason:
                self._last_exec_error = reason
            return
        if self._one_at_a_time and self._has_open_strategy():
            now_ms = int(time.time() * 1000)
            if now_ms - self._last_queue_block_log_ms >= 15000:
                self._last_queue_block_log_ms = now_ms
                pending = self._pending_candidates()
                if pending:
                    log.info(
                        "scanner queue waiting behind %s — best=%s pending=%s",
                        self._global_active_symbol(),
                        pending[0].symbol,
                        [c.symbol for c in pending[:5]],
                    )
            return
        candidates = self._pending_candidates()
        if not candidates:
            return
        # Try best first; fall through if blocked/failed without opening.
        for coin in candidates[:5]:
            before = bool(coin.short)
            self._try_open_short_entry(coin)
            if coin.short or (not before and self._exchange_has_short(coin.symbol)):
                return
            if self._one_at_a_time and self._has_open_strategy():
                return

    def status(self) -> dict[str, Any]:
        active_sym = self._global_active_symbol()
        pending = self._pending_candidates()
        active = sum(1 for c in self._coins.values() if c.active() or c.short or c.long1 or c.long2)
        can_exec, block_reason = self._order_session_ok()
        env_blocked, _ = _exec_env_blocked()
        return {
            "enabled": self._enabled,
            "exec_enabled": can_exec,
            "can_execute": can_exec,
            "exec_block": block_reason or None,
            "user_exec_halted": self._user_exec_halted,
            "exec_env_controlled": env_blocked,
            "last_exec_error": self._last_exec_error,
            "one_trade_at_a_time": self._one_at_a_time,
            "daily_limit": None,
            "trades_closed_today": self._trades_closed_today,
            "active_symbol": active_sym,
            "pending_count": len(pending),
            "best_pending": pending[0].symbol if pending else None,
            "symbols_tracked": len(self._coins),
            "watchlist": sum(1 for c in self._coins.values() if c.active()),
            "active_strategies": active,
            "partition_usd": self._partition_usd,
            "short_partition_pct": self._short_pct,
            "long1_partition_pct": self._long1_pct,
            "long2_partition_pct": self._long2_pct,
            "long_pullback_pct": LONG_HEDGE_PULLBACK_PCT,
            "short_pullback_pct": SHORT_TRAIL_PULLBACK_PCT,
            "short_tp_pct": SHORT_TP_PCT,
            "long_tp_pct": LONG_TP_PCT,
            "min_live_entry_pct": MIN_LIVE_ENTRY_PCT,
            "max_retrace_entry_pct": MAX_RETRACE_ENTRY_PCT,
            "entry_timeframe": ENTRY_TIMEFRAME,
            "risk_locked": self._risk_locked,
            "last_exec_latency_ms": self._last_exec_latency_ms,
            "execution_events": self._engine.events()[:12],
        }

    def load_symbols(self, symbols: list[str]) -> None:
        for s in symbols:
            sym = s.upper()
            if sym.endswith("USDT"):
                self._symbols_usdt.add(sym)
                if sym not in self._coins:
                    self._coins[sym] = CoinStrategy(symbol=sym)

    def on_tick(
        self,
        symbol: str,
        price: float,
        ts_ms: int | None = None,
        pct_24h: float | None = None,
        quote_vol_24h: float | None = None,
    ) -> None:
        if not self._enabled:
            return
        sym = symbol.upper()
        if sym not in self._symbols_usdt:
            return
        if price <= 0:
            return
        with self._lock:
            self._on_tick_locked(sym, price, ts_ms, pct_24h, quote_vol_24h)

    def _on_tick_locked(
        self,
        sym: str,
        price: float,
        ts_ms: int | None = None,
        pct_24h: float | None = None,
        quote_vol_24h: float | None = None,
    ) -> None:
        now_ms = int(ts_ms or time.time() * 1000)
        # Periodic exchange sync — catches orphan shorts outside scanner state.
        if not getattr(self._connector.cfg, "paper", False):
            if now_ms - self._last_reconcile_ms >= 5000:
                self._last_reconcile_ms = now_ms
                try:
                    self.reconcile_from_exchange()
                except Exception as e:
                    log.warning("reconcile_from_exchange: %s", e)
        coin = self._coins.get(sym)
        if not coin:
            coin = CoinStrategy(symbol=sym)
            self._coins[sym] = coin

        coin.price = price
        coin.last_update_ms = now_ms
        if pct_24h is not None:
            coin.pct_24h = pct_24h
        if quote_vol_24h is not None and quote_vol_24h >= 0:
            coin.quote_vol_24h = quote_vol_24h
        if getattr(self._connector.cfg, "paper", False):
            try:
                from paper_simulator import paper_store

                spread = price * 0.0001
                paper_store.set_tick(sym, price - spread, price + spread)
            except Exception:
                pass
        coin._history.append(PricePoint(now_ms, price))
        self._prune_history(coin, now_ms)
        coin.pct_1m, coin.pct_3m, coin.pct_5m, coin.pct_15m = self._rolling_pcts(coin, now_ms)
        coin.best_pct, coin.best_tf = self._best_move(coin)
        qualify_pct = self._entry_qualify_pct(coin)

        if coin.status in (STATUS_SCANNING, STATUS_CLOSED):
            if qualify_pct >= GAIN_THRESHOLD_PCT:
                coin.status = STATUS_WATCHING
                coin.highest_price = price
                coin.retrace_pct = 0.0
                coin.qualifying_pct = max(coin.qualifying_pct or 0.0, qualify_pct)
                coin.best_tf = ENTRY_TIMEFRAME
                self._emit_signal(coin, "watch")
        elif coin.status in (STATUS_WATCHING, STATUS_PENDING):
            if qualify_pct >= GAIN_THRESHOLD_PCT:
                coin.qualifying_pct = max(coin.qualifying_pct or 0.0, qualify_pct)
                coin.best_tf = ENTRY_TIMEFRAME
            if coin.highest_price is None or price > coin.highest_price:
                coin.highest_price = price
            if coin.highest_price and coin.highest_price > 0:
                coin.retrace_pct = ((coin.highest_price - price) / coin.highest_price) * 100.0
            self._demote_stale_pending(coin)
            if coin.status == STATUS_PENDING and coin.retrace_pct < RETRACE_ENTRY_PCT:
                coin.status = STATUS_WATCHING
            elif (
                self._entry_signal_ok(coin)
                and coin.status != STATUS_PENDING
            ):
                coin.status = STATUS_PENDING
                coin.best_tf = ENTRY_TIMEFRAME
                if not coin.entry_signal_key:
                    peak = coin.highest_price or price
                    coin.entry_signal_key = f"{sym}_{int(peak * 10000)}_{int((coin.qualifying_pct or 0) * 100)}"
                self._emit_signal(coin, "pending")
                # Ranked queue only — never fire first-to-pending from this tick.
            elif coin.status == STATUS_PENDING and self._entry_signal_ok(coin):
                pass  # wait for _maybe_execute_best_pending

        if coin.short or coin.long1 or coin.long2:
            self._manage_positions(coin)

        if self._one_at_a_time and self._order_session_ok()[0] and not self._has_open_strategy():
            self._maybe_execute_best_pending()
        elif not self._one_at_a_time and self._order_session_ok()[0]:
            self._maybe_execute_best_pending()

        self._maybe_broadcast()

    def snapshot_rows(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._snapshot_rows_locked()

    def _snapshot_rows_locked(self) -> list[dict[str, Any]]:
        rows = []
        for coin in self._coins.values():
            # Live market view: include any coin with recent price + meaningful move,
            # or an active strategy state — does not change entry/gain thresholds.
            hot_24h = abs(coin.pct_24h) >= 1.0
            hot_tf = max(
                abs(coin.pct_1m),
                abs(coin.pct_3m),
                abs(coin.pct_5m),
                abs(coin.pct_15m),
                abs(coin.best_pct),
            ) >= 0.5
            if not hot_tf and not hot_24h and not coin.active() and not coin.short:
                if coin.price <= 0:
                    continue
                # Still surface top-priced tracked names sparingly via absolute change
                if abs(coin.best_pct) < 0.35 and abs(coin.pct_24h) < 0.5:
                    continue
            rows.append(self._row(coin))
        rows.sort(
            key=lambda r: (
                {
                    STATUS_PENDING: 0,
                    STATUS_WATCHING: 1,
                    STATUS_SHORT: 2,
                    STATUS_LONG1: 3,
                    STATUS_LONG2: 4,
                }.get(r.get("status"), 5),
                -max(
                    abs(r.get("pctGain") or 0),
                    abs(r.get("pct1m") or 0),
                    abs(r.get("pct3m") or 0),
                    abs(r.get("pct5m") or 0),
                    abs(r.get("pct15m") or 0),
                    abs(r.get("pct24h") or 0) * 0.35,
                ),
            )
        )
        return rows[:MAX_WATCHLIST]

    def apply_volume_map(self, vol_map: dict[str, float]) -> int:
        n = 0
        for sym, vol in vol_map.items():
            coin = self._coins.get(sym.upper())
            if not coin:
                continue
            coin.quote_vol_24h = float(vol)
            n += 1
        return n

    def apply_funding_rate_map(self, rate_map: dict[str, float]) -> int:
        n = 0
        for sym, rate in rate_map.items():
            coin = self._coins.get(sym.upper())
            if not coin:
                continue
            coin.funding_rate = rate
            n += 1
        return n

    def apply_24h_pct_map(self, pct_map: dict[str, float]) -> int:
        """Refresh 24h % from REST ticker (does not change gain/retrace entry rules)."""
        if not pct_map:
            return 0
        n = 0
        for sym, pct in pct_map.items():
            coin = self._coins.get(sym.upper())
            if not coin:
                continue
            try:
                coin.pct_24h = float(pct)
                n += 1
            except (TypeError, ValueError):
                continue
        if n:
            self._last_broadcast = 0.0
            self._maybe_broadcast()
        return n

    def seed_history_from_klines(self, symbols: list[str] | None = None, limit_bars: int = 20) -> int:
        """
        Seed ~15–20 minutes of 1m closes so rolling 1m/3m/5m/15m tick % works immediately
        instead of waiting for live ticks to accumulate.
        """
        if not self._enabled:
            return 0
        syms = [s.upper() for s in (symbols or list(self._symbols_usdt)) if s]
        if not syms:
            return 0
        # Cap REST fan-out — prefer symbols already receiving ticks / high 24h move.
        scored: list[tuple[float, str]] = []
        for sym in syms:
            coin = self._coins.get(sym)
            score = abs(coin.pct_24h) if coin else 0.0
            if coin and coin.price > 0:
                score += 0.1
            scored.append((score, sym))
        scored.sort(reverse=True)
        pick = [s for _, s in scored[: min(60, len(scored))]]
        seeded = 0
        for sym in pick:
            coin = self._coins.get(sym)
            if not coin:
                continue
            if len(coin._history) >= max(8, limit_bars // 2):
                continue
            try:
                bars = self._connector.bars_interval(sym, interval="1m", count=limit_bars)
            except Exception as e:
                log.debug("seed klines %s: %s", sym, e)
                continue
            if not bars:
                continue
            now_ms = int(time.time() * 1000)
            for bar in bars:
                ts = int(bar.get("t") or 0)
                close = float(bar.get("c") or 0)
                if ts <= 0 or close <= 0:
                    continue
                # kline open time → approximate close time (+1m)
                coin._history.append(PricePoint(ts + 60_000, close))
            self._prune_history(coin, now_ms)
            if coin.price <= 0 and bars:
                coin.price = float(bars[-1].get("c") or 0)
                coin.last_update_ms = now_ms
            coin.pct_1m, coin.pct_3m, coin.pct_5m, coin.pct_15m = self._rolling_pcts(coin, now_ms)
            coin.best_pct, coin.best_tf = self._best_move(coin)
            seeded += 1
        if seeded:
            log.info("scanner seeded 1m history for %s symbols", seeded)
            self._last_broadcast = 0.0
            self._maybe_broadcast()
        return seeded

    def _row(self, coin: CoinStrategy) -> dict[str, Any]:
        return {
            "coin": coin.symbol.replace("USDT", ""),
            "symbol": coin.symbol,
            "price": round(coin.price, 8),
            "pctGain": round(coin.best_pct, 2),
            "pct1m": round(coin.pct_1m, 2),
            "pct3m": round(coin.pct_3m, 2),
            "pct5m": round(coin.pct_5m, 2),
            "pct15m": round(coin.pct_15m, 2),
            "pct24h": round(coin.pct_24h, 2),
            "volume24h": round(coin.quote_vol_24h, 2),
            "fundingRate": round(coin.funding_rate, 6) if coin.funding_rate is not None else None,
            "direction": "up" if coin.pct_24h > 0.05 else "down" if coin.pct_24h < -0.05 else "flat",
            "timeframe": coin.best_tf,
            "highestPrice": round(coin.highest_price or 0, 8),
            "retracePct": round(coin.retrace_pct, 2),
            "status": coin.status,
            "unrealizedPnl": round(coin.unrealized_pnl, 2),
        }

    def _prune_history(self, coin: CoinStrategy, now_ms: int) -> None:
        cutoff = now_ms - 16 * 60 * 1000
        while coin._history and coin._history[0].ts_ms < cutoff:
            coin._history.popleft()

    def _price_at(self, coin: CoinStrategy, now_ms: int, minutes: int) -> float | None:
        target = now_ms - minutes * 60 * 1000
        for pt in coin._history:
            if pt.ts_ms >= target:
                return pt.price
        return coin._history[0].price if coin._history else None

    def _rolling_pcts(self, coin: CoinStrategy, now_ms: int) -> tuple[float, float, float, float]:
        out: list[float] = []
        for m in TIMEFRAMES_MIN:
            old = self._price_at(coin, now_ms, m)
            if old and old > 0:
                out.append(((coin.price - old) / old) * 100.0)
            else:
                out.append(0.0)
        return out[0], out[1], out[2], out[3]

    def _best_move(self, coin: CoinStrategy) -> tuple[float, str]:
        pairs = [
            (coin.pct_1m, "1m"),
            (coin.pct_3m, "3m"),
            (coin.pct_5m, "5m"),
            (coin.pct_15m, "15m"),
        ]
        best = max(pairs, key=lambda x: x[0])
        return best[0], best[1]

    def _qty_for(self, symbol: str, price: float, leverage: int, partition_pct: float) -> float:
        if price <= 0:
            return 0.001
        margin_usd = self._partition_usd * partition_pct / 100.0
        notional = margin_usd * leverage
        qty = notional / price
        try:
            spec = self._connector.symbol_spec(symbol, pip_size=0.01)
            step = float(spec.get("stepSize") or 0.001)
            min_q = float(spec.get("minQty") or 0.001)
            from binance_connector import round_to_step

            qty = max(min_q, round_to_step(qty, step))
        except Exception:
            qty = max(0.001, round(qty, 3))
        return qty

    def _execute_pending_short(self, coin: CoinStrategy) -> None:
        """Fire the primary short once per entry signal — never re-send on every tick."""
        sym = coin.symbol
        if not self._entry_signal_ok(coin):
            return
        ok, _ = self._order_session_ok()
        if not ok or sym in self._in_flight or coin.short:
            return
        signal_id = f"{sym}_SHORT_{coin.entry_signal_key or coin.last_update_ms}"
        if coin.submitted_entry_signal_id == signal_id:
            entry = coin.price
            qty = self._qty_for(sym, entry, SHORT_LEVERAGE, self._short_pct)
            tp = entry * (1.0 - SHORT_TP_PCT / 100.0)
            self._recover_primary_short_entry(coin, sym, qty, entry, tp)
            return
        if self._one_at_a_time and self._has_open_strategy() and self._global_active_symbol() != sym:
            self._maybe_execute_best_pending()
            return
        self._try_open_short_entry(coin)

    def _try_open_short_entry(self, coin: CoinStrategy) -> None:
        sym = coin.symbol
        if coin.short:
            return
        if not self._entry_signal_ok(coin):
            return
        if sym in self._in_flight:
            return
        if self._one_at_a_time:
            active = self._global_active_symbol()
            if active and active != sym:
                return
        if self._in_entry_cooldown(sym):
            log.info("scanner SHORT cooldown %s — skip re-entry", sym)
            return
        if pair_gate.is_close_pending(sym):
            return
        # Never open a primary short into an orphan long — reconcile flattens those first.
        if self._exchange_has_orphan_long(sym):
            log.warning("scanner SHORT blocked %s: orphan exchange long open", sym)
            self._last_exec_error = f"{sym}: orphan_exchange_long"
            return
        # Never stack scanner Short on top of an existing exchange short (manual or orphan).
        if self._exchange_has_short(sym):
            log.warning("scanner SHORT blocked %s: exchange short already open", sym)
            self._last_exec_error = f"{sym}: exchange_short_already_open"
            # Adopt the existing short so we manage it instead of waiting to stack.
            try:
                qty = float(getattr(self._connector, "exchange_short_qty", lambda _s: 0)(sym) or 0)
                leg = self._exchange_short_leg(sym) or {}
                entry = float(leg.get("price_open") or coin.price or 0)
                if qty > 1e-12 and entry > 0:
                    tp = entry * (1.0 - SHORT_TP_PCT / 100.0)
                    self._recover_primary_short_entry(coin, sym, qty, entry, tp)
            except Exception as e:
                log.warning("scanner SHORT adopt %s: %s", sym, e)
            return
        ok_iso, _ = pair_gate.can_open(sym, self._global_active_symbol, self._exchange_positions)
        if not ok_iso:
            return
        if not getattr(self._connector.cfg, "paper", False):
            ok_hedge, hedge_err = self._connector.ensure_hedge_mode()
            if not ok_hedge:
                self._last_exec_error = f"{sym}: hedge_mode_required:{hedge_err}"
                log.warning("scanner SHORT blocked %s: %s", sym, hedge_err)
                return
        self._in_flight.add(sym)
        signal_id = f"{sym}_SHORT_{coin.entry_signal_key or coin.last_update_ms}"
        try:
            entry = coin.price
            qty = self._qty_for(sym, entry, SHORT_LEVERAGE, self._short_pct)
            tp = entry * (1.0 - SHORT_TP_PCT / 100.0)
            if coin.submitted_entry_signal_id == signal_id:
                self._recover_primary_short_entry(coin, sym, qty, entry, tp)
                return
            coin.submitted_entry_signal_id = signal_id
            coin.entry_submit_ms = int(time.time() * 1000)
            signal = ExecutionSignal(
                symbol=sym,
                side="SELL",
                quantity=qty,
                reference_price=entry,
                leverage=SHORT_LEVERAGE,
                magic=MAGIC_SHORT,
                leg="SHORT",
                tp=tp,
                signal_id=signal_id,
                signal_ts_ms=int(time.time() * 1000),
                partition_usd=self._partition_usd,
                partition_pct=self._short_pct,
                margin_type="ISOLATED",
            )
            self._emit_signal(coin, "executing")
            r = self._engine.execute(signal)
            self._last_exec_latency_ms = r.latency_ms or None
            if r.ok:
                fill = float(r.fill_price or entry)
                fill_qty = float(r.quantity or qty)
                # Prefer live exchange qty so partial fills / rounding do not desync closes.
                try:
                    ex_qty = float(getattr(self._connector, "exchange_short_qty", lambda _s: 0)(sym) or 0)
                    if ex_qty > fill_qty:
                        fill_qty = ex_qty
                except Exception:
                    pass
                tp = fill * (1.0 - SHORT_TP_PCT / 100.0)
                coin.short = LegPosition("SELL", fill, fill_qty, SHORT_LEVERAGE, MAGIC_SHORT, tp)
                coin.status = STATUS_SHORT
                coin.short_trough_price = fill
                coin.short_adverse_peak_pct = 0.0
                coin.long1_was_closed = False
                coin.long2_was_closed = False
                coin.long1_peak_price = None
                coin.long2_peak_price = None
                self._mark_short_opened(coin, sym)
                if hasattr(self._connector, "ensure_exchange_leverage"):
                    self._connector.ensure_exchange_leverage(sym, SHORT_LEVERAGE)
                self._last_exec_error = None
                self._emit_signal(coin, "entered")
                log.info("scanner SHORT %s qty=%s @ %s order=%s latency_ms=%s", sym, fill_qty, fill, r.order_id, r.latency_ms)
            elif r.stage in ("duplicate", "in_flight") or "duplicate" in str(r.error or "").lower():
                if not self._recover_primary_short_entry(coin, sym, qty, entry, tp):
                    self._last_exec_error = None
                    log.info("scanner %s entry already submitted (%s) — skipping re-send", sym, r.stage or r.error)
            else:
                # Sticky submit: do not clear on transient failure — recover if filled, else wait TTL.
                if not self._recover_primary_short_entry(coin, sym, qty, entry, tp):
                    self._clear_stale_submit(coin, "entry")
                err = str(r.error or "order_failed")
                self._last_exec_error = f"{sym}: {err}"
                log.warning("scanner SHORT failed %s: %s latency_ms=%s", sym, err, r.latency_ms)
                if not coin.short:
                    coin.status = STATUS_PENDING
        finally:
            self._in_flight.discard(sym)

    def _try_open_long1(self, coin: CoinStrategy) -> None:
        sym = coin.symbol
        if not self._long1_entry_allowed(coin):
            return
        if sym in self._in_flight:
            return
        if pair_gate.is_close_pending(sym):
            return
        self._in_flight.add(sym)
        signal_id = f"{sym}_LONG1_{coin.entry_signal_key or coin.last_update_ms}"
        try:
            entry = coin.price
            qty = self._qty_for(sym, entry, LONG1_LEVERAGE, self._long1_pct)
            tp = entry * (1.0 + LONG_TP_PCT / 100.0)
            if coin.submitted_long1_signal_id == signal_id:
                if coin.long1:
                    return
                self._recover_long1_entry(coin, sym, qty, entry, tp)
                return
            coin.submitted_long1_signal_id = signal_id
            coin.long1_submit_ms = int(time.time() * 1000)
            signal = ExecutionSignal(
                symbol=sym,
                side="BUY",
                quantity=qty,
                reference_price=entry,
                leverage=LONG1_LEVERAGE,
                magic=MAGIC_LONG1,
                leg="LONG1",
                tp=tp,
                signal_id=signal_id,
                signal_ts_ms=int(time.time() * 1000),
                partition_usd=self._partition_usd,
                partition_pct=self._long1_pct,
                margin_type="ISOLATED",
            )
            self._emit_signal(coin, "long1_executing")
            r = self._engine.execute(signal)
            self._last_exec_latency_ms = r.latency_ms or None
            if r.ok:
                fill = float(r.fill_price or entry)
                tp = fill * (1.0 + LONG_TP_PCT / 100.0)
                coin.long1 = LegPosition("BUY", fill, qty, LONG1_LEVERAGE, MAGIC_LONG1, tp)
                coin.status = STATUS_LONG1
                coin.long1_peak_price = fill
                self._mark_long1_opened(coin, sym)
                if hasattr(self._connector, "ensure_exchange_leverage"):
                    self._connector.ensure_exchange_leverage(sym, LONG1_LEVERAGE)
                self._last_exec_error = None
                self._emit_signal(coin, "long1_entered")
                log.info("scanner LONG1 %s qty=%s @ %s order=%s latency_ms=%s", sym, qty, fill, r.order_id, r.latency_ms)
            elif r.stage in ("duplicate", "in_flight") or "duplicate" in str(r.error or "").lower():
                if not self._recover_long1_entry(coin, sym, qty, entry, tp):
                    log.info("scanner %s long1 already submitted (%s) — skipping re-send", sym, r.stage or r.error)
            else:
                if not self._recover_long1_entry(coin, sym, qty, entry, tp):
                    self._clear_stale_submit(coin, "long1")
                err = str(r.error or "order_failed")
                self._last_exec_error = f"{sym} LONG1: {err}"
                log.warning("scanner LONG1 failed %s: %s latency_ms=%s", sym, err, r.latency_ms)
        finally:
            self._in_flight.discard(sym)

    def _try_open_long2(self, coin: CoinStrategy) -> None:
        sym = coin.symbol
        if not self._long2_entry_allowed(coin):
            return
        if sym in self._in_flight:
            return
        if pair_gate.is_close_pending(sym):
            return
        self._in_flight.add(sym)
        signal_id = f"{sym}_LONG2_{coin.entry_signal_key or coin.last_update_ms}"
        try:
            entry = coin.price
            qty = self._qty_for(sym, entry, LONG2_LEVERAGE, self._long2_pct)
            tp = entry * (1.0 + LONG_TP_PCT / 100.0)
            if coin.submitted_long2_signal_id == signal_id:
                if coin.long2:
                    return
                self._recover_long2_entry(coin, sym, qty, entry, tp)
                return
            coin.submitted_long2_signal_id = signal_id
            coin.long2_submit_ms = int(time.time() * 1000)
            signal = ExecutionSignal(
                symbol=sym,
                side="BUY",
                quantity=qty,
                reference_price=entry,
                leverage=LONG2_LEVERAGE,
                magic=MAGIC_LONG2,
                leg="LONG2",
                tp=tp,
                signal_id=signal_id,
                signal_ts_ms=int(time.time() * 1000),
                partition_usd=self._partition_usd,
                partition_pct=self._long2_pct,
                margin_type="ISOLATED",
            )
            self._emit_signal(coin, "long2_executing")
            r = self._engine.execute(signal)
            self._last_exec_latency_ms = r.latency_ms or None
            if r.ok:
                fill = float(r.fill_price or entry)
                tp = fill * (1.0 + LONG_TP_PCT / 100.0)
                coin.long2 = LegPosition("BUY", fill, qty, LONG2_LEVERAGE, MAGIC_LONG2, tp)
                coin.long2_peak_price = fill
                coin.status = STATUS_LONG2
                self._mark_long2_opened(coin)
                if hasattr(self._connector, "ensure_exchange_leverage"):
                    self._connector.ensure_exchange_leverage(sym, LONG2_LEVERAGE)
                self._last_exec_error = None
                self._emit_signal(coin, "long2_entered")
                log.info("scanner LONG2 %s qty=%s @ %s order=%s latency_ms=%s", sym, qty, fill, r.order_id, r.latency_ms)
            elif r.stage in ("duplicate", "in_flight") or "duplicate" in str(r.error or "").lower():
                if not self._recover_long2_entry(coin, sym, qty, entry, tp):
                    log.info("scanner %s long2 already submitted (%s) — skipping re-send", sym, r.stage or r.error)
            else:
                if not self._recover_long2_entry(coin, sym, qty, entry, tp):
                    self._clear_stale_submit(coin, "long2")
                err = str(r.error or "order_failed")
                self._last_exec_error = f"{sym} LONG2: {err}"
                log.warning("scanner LONG2 failed %s: %s latency_ms=%s", sym, err, r.latency_ms)
        finally:
            self._in_flight.discard(sym)

    def _try_open_recovery_long(self, coin: CoinStrategy) -> None:
        if coin.long1 is None and not coin.long1_was_closed:
            self._try_open_long1(coin)
        elif coin.long2 is None:
            self._try_open_long2(coin)

    def _try_open_short(self, coin: CoinStrategy) -> None:
        self._try_open_short_entry(coin)

    def _try_open_long(self, coin: CoinStrategy, leg: int) -> None:
        if leg == 1:
            self._try_open_long1(coin)
        elif leg == 2:
            self._try_open_long2(coin)

    def _leg_pnl(self, leg: LegPosition, price: float) -> float:
        if leg.side == "BUY":
            return (price - leg.entry) * leg.qty
        return (leg.entry - price) * leg.qty

    def _manage_positions(self, coin: CoinStrategy) -> None:
        if not self._ensure_pair_coherence(coin):
            return

        sym = coin.symbol
        if (coin.short or coin.long1 or coin.long2) and not getattr(self._connector.cfg, "paper", False):
            if hasattr(self._connector, "ensure_exchange_leverage"):
                from leverage_policy import symbol_exchange_leverage

                has_long = bool(coin.long1) or bool(coin.long2)
                self._connector.ensure_exchange_leverage(sym, symbol_exchange_leverage(has_recovery_long=has_long))

        price = coin.price
        if not coin.short and not coin.long1 and not coin.long2:
            coin.unrealized_pnl = 0.0
            return

        short_pnl = self._leg_pnl(coin.short, price) if coin.short else 0.0
        long1_pnl = self._leg_pnl(coin.long1, price) if coin.long1 else 0.0
        long2_pnl = self._leg_pnl(coin.long2, price) if coin.long2 else 0.0
        coin.unrealized_pnl = short_pnl + long1_pnl + long2_pnl
        cost_buf = self._exit_cost_buffer_usd()

        if self._effective_smart_exit_pct() > 0 and self._partition_usd > 0:
            smart_target = (
                self._partition_usd * self._effective_smart_exit_pct() / 100.0 + cost_buf
            )
            # Naked short still eligible for Long 1 — let the hard TP (-2.5%) handle winners;
            # smart-exit was closing small moves before any +2% recovery pump.
            if (
                coin.unrealized_pnl >= smart_target
                and not (self._recovery_still_eligible(coin) and coin.long1 is None and coin.long2 is None)
            ):
                log.info(
                    "scanner %s SMART_EXIT pnl=%.4f target=%.4f",
                    sym,
                    coin.unrealized_pnl,
                    smart_target,
                )
                self._close_all(coin, "SMART_EXIT")
                return

        if coin.short:
            adverse = self._short_adverse_pct(coin)
            if adverse > coin.short_adverse_peak_pct:
                coin.short_adverse_peak_pct = adverse

        # Long 1 @ +2%; Long 2 @ +4% — independent checks so a gap to +4% can arm both.
        if coin.short and coin.long1 is None and self._long1_entry_allowed(coin):
            self._try_open_long1(coin)

        if coin.short and coin.long2 is None and self._long2_entry_allowed(coin):
            self._try_open_long2(coin)

        # Long 1: TP at +2.5% or 0.5% retrace from its own peak — closes that leg only.
        if coin.long1:
            if coin.long1_peak_price is None or price > coin.long1_peak_price:
                coin.long1_peak_price = price
            if coin.long1.tp_price and price >= coin.long1.tp_price:
                self._close_leg(coin, "long1", reason="LONG1_TP")
            else:
                peak = float(coin.long1_peak_price or price)
                pullback_pct = self._long_hedge_pullback_pct(peak, price)
                if pullback_pct >= self._effective_long_pullback_pct():
                    log.info(
                        "scanner %s LONG1_PULLBACK %.2f%% (peak=%s price=%s entry=%s)",
                        coin.symbol,
                        pullback_pct,
                        peak,
                        price,
                        coin.long1.entry,
                    )
                    self._close_leg(coin, "long1", reason="LONG1_PULLBACK")

        # Long 2: TP at +2.5% or 0.5% retrace from its own peak — closed immediately.
        if coin.long2:
            if coin.long2_peak_price is None or price > coin.long2_peak_price:
                coin.long2_peak_price = price
            if coin.long2.tp_price and price >= coin.long2.tp_price:
                self._close_leg(coin, "long2", reason="LONG2_TP")
            else:
                peak = float(coin.long2_peak_price or price)
                pullback_pct = self._long_hedge_pullback_pct(peak, price)
                if pullback_pct >= self._effective_long_pullback_pct():
                    log.info(
                        "scanner %s LONG2_PULLBACK %.2f%% (peak=%s price=%s entry=%s)",
                        coin.symbol,
                        pullback_pct,
                        peak,
                        price,
                        coin.long2.entry,
                    )
                    self._close_leg(coin, "long2", reason="LONG2_PULLBACK")

        # Primary short: hard TP at -2.5%; trail only after profitable MFE (never a hard stop).
        if coin.short:
            if coin.short_trough_price is None or price < coin.short_trough_price:
                coin.short_trough_price = price
            short_exit_reason = ""
            if coin.short.tp_price and price <= coin.short.tp_price:
                short_exit_reason = "SHORT_TP"
            elif self._short_pullback_allowed(coin, price):
                trough = float(coin.short_trough_price or price)
                bounce_pct = ((price - trough) / trough) * 100.0 if trough > 0 else 0.0
                log.info(
                    "scanner %s SHORT_PULLBACK %.2f%% (trough=%s price=%s entry=%s)",
                    coin.symbol,
                    bounce_pct,
                    trough,
                    price,
                    coin.short.entry,
                )
                short_exit_reason = "SHORT_PULLBACK"
            if short_exit_reason:
                # Recovery longs may never outlive the primary short.
                self._close_all(coin, short_exit_reason)
                return

    def _close_leg(self, coin: CoinStrategy, leg_name: str, reason: str = "") -> None:
        sym = coin.symbol
        if leg_name == "long1":
            leg = coin.long1
        elif leg_name == "long2":
            leg = coin.long2
        elif leg_name == "short":
            leg = coin.short
        else:
            leg = None
        if not leg:
            return
        # The primary short can never be closed alone — that would orphan the recovery longs.
        if leg_name == "short" and (coin.long1 or coin.long2):
            self._close_all(coin, f"{reason or 'SHORT_CLOSE'}_ORPHAN_FLATTEN")
            return
        pair_gate.begin_close(sym)
        try:
            # Primary short: flatten the full SHORT side (dust-safe).
            # Recovery Long 1 / Long 2 share the exchange LONG — close only this leg's qty
            # while the sibling recovery leg is still open, or the sibling gets wiped.
            sibling_long = None
            if leg_name == "long1":
                sibling_long = coin.long2
            elif leg_name == "long2":
                sibling_long = coin.long1
            close_vol: float | None = None
            if leg.side == "BUY" and sibling_long is not None:
                close_vol = max(float(leg.qty or 0), 0.0)
                if close_vol <= 0:
                    log.warning("scanner close leg %s %s: missing qty with sibling long open", sym, leg_name)
                    return

            if hasattr(self._connector, "close_by_position_side"):
                if leg.side == "SELL":
                    r = self._connector.close_by_position_side(sym, "SHORT", None)
                else:
                    r = self._connector.close_by_position_side(sym, "LONG", close_vol)
            else:
                r = self._connector.close_leg(sym, leg.magic, close_vol)
            if not r.get("ok"):
                log.warning("scanner close leg failed %s %s: %s", sym, leg_name, r.get("error") or r)
                return
            # Live only: verify expected residual before clearing scanner state.
            if not getattr(self._connector.cfg, "paper", False):
                if leg.side == "SELL" and self._exchange_has_short(sym):
                    log.warning("scanner close leg %s %s reported ok but SHORT still open — forcing", sym, leg_name)
                    try:
                        if hasattr(self._connector, "close_by_position_side"):
                            self._connector.close_by_position_side(sym, "SHORT", None)
                        elif hasattr(self._connector, "close_position"):
                            self._connector.close_position(sym, None)
                        else:
                            return
                    except Exception as e:
                        log.warning("scanner force flatten short %s: %s", sym, e)
                        return
                elif leg.side == "BUY":
                    still_long = self._exchange_has_long(sym)
                    if sibling_long is None and still_long:
                        log.warning(
                            "scanner close leg %s %s reported ok but LONG still open — forcing long side",
                            sym,
                            leg_name,
                        )
                        try:
                            if hasattr(self._connector, "close_by_position_side"):
                                self._connector.close_by_position_side(sym, "LONG", None)
                            else:
                                return
                        except Exception as e:
                            log.warning("scanner force flatten long %s: %s", sym, e)
                            return
                    elif sibling_long is not None and not still_long:
                        # Partial close took the whole long — sibling is gone on exchange.
                        log.warning(
                            "scanner %s %s close flattened shared LONG — clearing sibling recovery leg",
                            sym,
                            leg_name,
                        )
                        if leg_name == "long1":
                            coin.long2 = None
                            coin.long2_peak_price = None
                            coin.long2_was_closed = True
                        else:
                            coin.long1 = None
                            coin.long1_peak_price = None
                            coin.long1_was_closed = True
            if leg_name == "short":
                coin.short = None
                coin.short_trough_price = None
                coin.short_was_closed = True
                coin.status = STATUS_CLOSED
            elif leg_name == "long1":
                coin.long1 = None
                coin.long1_peak_price = None
                coin.long1_was_closed = True
                coin.status = STATUS_LONG2 if coin.long2 else (STATUS_SHORT if coin.short else STATUS_CLOSED)
            elif leg_name == "long2":
                coin.long2 = None
                coin.long2_peak_price = None
                coin.long2_was_closed = True
                coin.status = STATUS_LONG1 if coin.long1 else (STATUS_SHORT if coin.short else STATUS_CLOSED)
            # Shared LONG went flat — drop any phantom recovery sibling.
            if leg.side == "BUY" and not getattr(self._connector.cfg, "paper", False):
                if not self._exchange_has_long(sym):
                    if coin.long1:
                        coin.long1 = None
                        coin.long1_peak_price = None
                        coin.long1_was_closed = True
                    if coin.long2:
                        coin.long2 = None
                        coin.long2_peak_price = None
                        coin.long2_was_closed = True
                    coin.status = STATUS_SHORT if coin.short else STATUS_CLOSED
            self._refresh_exchange_tps(coin)
            self._connector.invalidate_positions_cache()
            if reason:
                log.info("scanner closed leg %s %s reason=%s", sym, leg_name, reason)
        finally:
            pair_gate.end_close(sym)

    def _close_succeeded(self, close_result: dict[str, Any], symbol: str | None = None) -> bool:
        """Only treat flatten as success when exchange is actually flat (or already_flat)."""
        if close_result.get("note") == "already_flat":
            return True
        if not close_result.get("ok"):
            return False
        if close_result.get("error") == "partial_close_remaining_legs":
            return False
        if close_result.get("remaining"):
            return False
        sym = (symbol or "").upper()
        if sym and not getattr(self._connector.cfg, "paper", False):
            try:
                left = [
                    p
                    for p in (self._connector.positions(sym, force=True) or [])
                    if float(p.get("volume") or 0) > 1e-12
                ]
                if left:
                    return False
            except Exception as e:
                log.warning("close success verify %s: %s", sym, e)
                return False
        return True

    def _close_all(self, coin: CoinStrategy, reason: str) -> dict[str, Any]:
        sym = coin.symbol
        pair_gate.begin_close(sym)
        t0 = time.perf_counter()
        close_result: dict[str, Any] = {"ok": True, "closed": [], "broker": "binance"}
        try:
            if getattr(self._connector.cfg, "paper", False):
                closed_legs: list[dict[str, Any]] = []
                all_ok = True
                if coin.short:
                    r = self._connector.close_leg(sym, coin.short.magic, coin.short.qty)
                    if r.get("ok"):
                        closed_legs.append({**r, "side": "SELL", "symbol": sym})
                    else:
                        all_ok = False
                for hedge in (coin.long1, coin.long2):
                    if not hedge:
                        continue
                    r = self._connector.close_leg(sym, hedge.magic, hedge.qty)
                    if r.get("ok"):
                        closed_legs.append({**r, "side": "BUY", "symbol": sym})
                    else:
                        all_ok = False
                close_result = {"ok": all_ok, "closed": closed_legs, "broker": "binance"}
            else:
                try:
                    live = self._connector.positions(sym, force=True)
                except Exception:
                    live = []
                if live:
                    close_result = self._connector.close_position(sym, None)
                else:
                    close_result = {"ok": True, "closed": [], "broker": "binance", "note": "already_flat"}
            if self._close_succeeded(close_result, sym):
                self._reset_coin_state(coin)
                self._arm_entry_cooldown(sym, reason or "scanner_close")
                self._connector.invalidate_positions_cache()
                latency_ms = round((time.perf_counter() - t0) * 1000, 1)
                close_result["latency_ms"] = float(close_result.get("latency_ms") or latency_ms)
                pair_gate.record_order(
                    symbol=sym,
                    side="CLOSE",
                    order_id=(close_result.get("closed") or [{}])[0].get("order") if close_result.get("closed") else None,
                    latency_ms=close_result["latency_ms"],
                    source="scanner",
                )
                log.info("scanner closed %s reason=%s latency_ms=%s", sym, reason, close_result["latency_ms"])
                self._bump_trades_closed()
                if self._one_at_a_time:
                    self._maybe_execute_best_pending()
            else:
                # Keep scanner state — live legs still open (e.g. -4131 partial).
                self._last_exec_error = f"{sym}: {close_result.get('error') or 'close_incomplete'}"
                log.warning(
                    "scanner close incomplete %s reason=%s error=%s remaining=%s — state preserved",
                    sym,
                    reason,
                    close_result.get("error"),
                    close_result.get("remaining"),
                )
                close_result["ok"] = False
                close_result["error"] = close_result.get("error") or "close_incomplete"
            return close_result
        finally:
            pair_gate.end_close(sym)

    def _maybe_broadcast(self) -> None:
        if not self._on_snapshot:
            return
        now = time.time()
        # Throttle harder under miniTicker load so REST/login/WS ping stay responsive.
        min_gap = 1.0
        if now - self._last_broadcast < min_gap:
            return
        self._last_broadcast = now
        try:
            self._on_snapshot(self.full_snapshot())
        except Exception as e:
            log.warning("snapshot broadcast: %s", e)
