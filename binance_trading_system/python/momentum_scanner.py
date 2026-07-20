"""
Tick-by-tick multi-coin momentum scanner + retracement strategy.

Monitors 1m / 3m / 5m / 15m rolling % on every price tick (max study window 15m).
Entry: 15m move >= 5% gain, then >= 0.7% retrace from peak → Long (50% partition, 5x).
Recovery: -2% adverse from Long → Short1 (40%, 10x); at -4% adverse from Long → Short2 (40%, 10x).
Each recovery leg requires confirmed anchor long, settle delay, and tracked adverse peak (no guess).
Each leg TP at 2.5%; optional 0.5% pullback exit remains as backup.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from execution_engine import ExecutionEngine, ExecutionSignal
from leverage_policy import LONG1_LEVERAGE, LONG2_LEVERAGE, SHORT_LEVERAGE
from pair_isolation import pair_gate

log = logging.getLogger("momentum_scanner")

GAIN_THRESHOLD_PCT = float(os.environ.get("SCANNER_GAIN_PCT", "5.0"))
RETRACE_ENTRY_PCT = float(os.environ.get("SCANNER_RETRACE_PCT", "0.7"))
# Live 15m must still be hot at entry — blocks stale latched pumps (e.g. 15m already -16%).
MIN_LIVE_ENTRY_PCT = float(os.environ.get("SCANNER_MIN_LIVE_ENTRY_PCT", "2.0"))
# Do not short after the move is largely over (chasing a dump from peak).
MAX_RETRACE_ENTRY_PCT = float(os.environ.get("SCANNER_MAX_RETRACE_ENTRY_PCT", "12.0"))
SHORT_TP_PCT = float(os.environ.get("SCANNER_SHORT_TP_PCT", "2.5"))
LONG1_ADVERSE_PCT = float(os.environ.get("SCANNER_LONG1_PCT", "2.0"))
LONG2_ADVERSE_PCT = float(os.environ.get("SCANNER_LONG2_PCT", "4.0"))
LONG_TP_PCT = float(os.environ.get("SCANNER_LONG_TP_PCT", "2.5"))
LONG_BOTH_PULLBACK_PCT = float(os.environ.get("SCANNER_LONG_PULLBACK_PCT", "0.5"))
LONG_ENTRY_DELAY_MS = int(os.environ.get("SCANNER_LONG_DELAY_MS", "3000"))
SMART_EXIT_NET_PCT = float(os.environ.get("SCANNER_SMART_EXIT_PCT", "1.0"))
# Leverage fixed in leverage_policy.py — SHORT 5x, LONG1/LONG2 10x only.
DEFAULT_PARTITION_USD = float(os.environ.get("SCANNER_PARTITION_USD", os.environ.get("SCANNER_RISK_USDT", "100")))
SHORT_PARTITION_PCT = float(os.environ.get("SCANNER_SHORT_PARTITION_PCT", "50"))
LONG1_PARTITION_PCT = float(os.environ.get("SCANNER_LONG1_PARTITION_PCT", "40"))
LONG2_PARTITION_PCT = float(os.environ.get("SCANNER_LONG2_PARTITION_PCT", "40"))
MAX_WATCHLIST = int(os.environ.get("SCANNER_MAX_WATCH", "80"))
ONE_TRADE_AT_A_TIME = os.environ.get("SCANNER_ONE_TRADE", "1").strip().lower() not in ("0", "false", "off")
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
    recovery_peak_price: float | None = None
    long1_opened_ms: int = 0
    long2_opened_ms: int = 0
    long1_adverse_peak_pct: float = 0.0
    long2_adverse_peak_pct: float = 0.0
    short_opened_ms: int = 0
    short_adverse_peak_pct: float = 0.0
    independent_legs_mode: bool = False
    unrealized_pnl: float = 0.0
    last_update_ms: int = 0
    entry_signal_key: str = ""
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
        self._last_broadcast = 0.0
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
            # Pair legs (Long1/Long2/Short) share one slot — scanner enforces one symbol via _has_open_strategy().
            open_trade_count=lambda: 0,
        )
        self._engine.set_isolation_hooks(
            can_open=lambda sym: pair_gate.can_open(
                sym, self._global_active_symbol, self._exchange_positions
            ),
            close_pending=pair_gate.is_close_pending,
        )
        self._last_exec_latency_ms: float | None = None

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
        """Live Binance short leg for symbol — required before any recovery long."""
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
        """Live Binance long leg for symbol — required before Long2 / recovery short."""
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
            return bool(coin and coin.long1)
        fn = getattr(self._connector, "exchange_long_qty", None)
        if callable(fn):
            return float(fn(symbol) or 0) > 1e-12
        return self._exchange_long_leg(symbol) is not None

    def _exchange_has_orphan_long(self, symbol: str) -> bool:
        """Standalone long on exchange with no short — allowed in long-first entry phase."""
        if getattr(self._connector.cfg, "paper", False):
            return False
        long_fn = getattr(self._connector, "exchange_long_qty", None)
        short_fn = getattr(self._connector, "exchange_short_qty", None)
        if not callable(long_fn) or not callable(short_fn):
            return False
        return float(long_fn(symbol) or 0) > 1e-12 and float(short_fn(symbol) or 0) <= 1e-12

    def _sync_long_entry_from_exchange(self, coin: CoinStrategy, leg: int) -> float:
        leg_pos = coin.long1 if leg == 1 else coin.long2
        if not leg_pos:
            return 0.0
        entry = float(leg_pos.entry or 0)
        if getattr(self._connector.cfg, "paper", False):
            return entry
        ex_leg = self._exchange_long_leg(coin.symbol)
        if ex_leg:
            ex_entry = float(ex_leg.get("price_open") or 0)
            if ex_entry > 0:
                entry = ex_entry
                leg_pos.entry = ex_entry
        return entry

    def _long_adverse_pct(self, coin: CoinStrategy, leg: int) -> float:
        """Adverse move vs a long leg — price falling below entry."""
        leg_pos = coin.long1 if leg == 1 else coin.long2
        if not leg_pos:
            return 0.0
        entry = self._sync_long_entry_from_exchange(coin, leg)
        if entry <= 0 or coin.price <= 0:
            return 0.0
        return ((entry - coin.price) / entry) * 100.0

    def _short1_entry_allowed(self, coin: CoinStrategy) -> bool:
        """Short1 after primary long + settle delay when price falls 2% from long entry."""
        if not coin.long1 or coin.long1_was_closed:
            return False
        if coin.short is not None or coin.short_was_closed:
            return False
        if not self._exchange_has_long(coin.symbol):
            log.warning("scanner SHORT1 blocked %s: no exchange long", coin.symbol)
            return False
        if not self._long1_settle_elapsed(coin):
            return False
        if coin.long1_adverse_peak_pct < LONG1_ADVERSE_PCT:
            return False
        return True

    def _short2_entry_allowed(self, coin: CoinStrategy) -> bool:
        """Short2 after Short1 when price falls 4% from primary long entry."""
        if not coin.long1 or not coin.short:
            return False
        if coin.long2 is not None or coin.long2_was_closed:
            return False
        if not self._short1_settle_elapsed(coin):
            return False
        if coin.long1_adverse_peak_pct < LONG2_ADVERSE_PCT:
            return False
        return True

    def _long1_settle_elapsed(self, coin: CoinStrategy) -> bool:
        if LONG_ENTRY_DELAY_MS <= 0:
            return True
        if not coin.long1_opened_ms:
            return False
        return int(time.time() * 1000) - coin.long1_opened_ms >= LONG_ENTRY_DELAY_MS

    def _short1_settle_elapsed(self, coin: CoinStrategy) -> bool:
        if LONG_ENTRY_DELAY_MS <= 0:
            return True
        if not coin.short_opened_ms:
            return False
        return int(time.time() * 1000) - coin.short_opened_ms >= LONG_ENTRY_DELAY_MS

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

    def _adopt_exchange_long1(
        self,
        coin: CoinStrategy,
        symbol: str,
        fallback_qty: float,
        fallback_entry: float,
        tp: float,
    ) -> bool:
        sym = symbol.upper()
        leg = self._exchange_long_leg(sym)
        if not leg:
            return False
        fill = float(leg.get("price_open") or fallback_entry or coin.price or 0)
        qty = float(leg.get("volume") or fallback_qty or 0)
        if fill <= 0 or qty <= 1e-12:
            return False
        coin.long1 = LegPosition("BUY", fill, qty, SHORT_LEVERAGE, MAGIC_LONG1, tp)
        coin.status = STATUS_LONG1
        coin.long1_peak_price = fill
        coin.long1_adverse_peak_pct = 0.0
        coin.long2_adverse_peak_pct = 0.0
        self._mark_long1_opened(coin, sym)
        self._last_exec_error = None
        self._emit_signal(coin, "entered")
        log.info("scanner adopted exchange LONG %s qty=%s @ %s", sym, qty, fill)
        return True

    def _adopt_exchange_short(
        self,
        coin: CoinStrategy,
        symbol: str,
        fallback_qty: float,
        fallback_entry: float,
        tp: float,
    ) -> bool:
        """Recover scanner short state when Binance filled but ACK was lost / duplicate blocked."""
        sym = symbol.upper()
        leg = self._exchange_short_leg(sym)
        if not leg:
            return False
        fill = float(leg.get("price_open") or fallback_entry or coin.price or 0)
        qty = float(leg.get("volume") or fallback_qty or 0)
        if fill <= 0 or qty <= 1e-12:
            return False
        coin.short = LegPosition("SELL", fill, qty, LONG1_LEVERAGE, MAGIC_SHORT, tp)
        coin.status = STATUS_SHORT
        coin.recovery_peak_price = fill
        self._mark_short_opened(coin, sym)
        self._last_exec_error = None
        self._emit_signal(coin, "short1_entered")
        log.info("scanner adopted exchange SHORT %s qty=%s @ %s", sym, qty, fill)
        return True

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

    def _entry_signal_ok(self, coin: CoinStrategy) -> bool:
        latched = (coin.qualifying_pct or 0.0) >= GAIN_THRESHOLD_PCT
        return latched and self._live_entry_ok(coin) and self._retrace_entry_ok(coin)

    def _demote_stale_pending(self, coin: CoinStrategy) -> None:
        """Drop pending queue rows whose pump died or dump already finished."""
        if coin.status != STATUS_PENDING or coin.long1:
            return
        if not self._live_entry_ok(coin) or float(coin.retrace_pct or 0.0) > MAX_RETRACE_ENTRY_PCT:
            coin.status = STATUS_WATCHING
            coin.qualifying_pct = 0.0
            coin.entry_signal_key = None

    def _persist_risk_config(self) -> None:
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
            log.info(
                "scanner risk loaded partition=$%s locked=%s exec_halted=%s",
                self._partition_usd,
                self._risk_locked,
                self._user_exec_halted,
            )
        except Exception as e:
            log.warning("load risk config: %s", e)

    def set_risk_config(
        self,
        partition_usd: float | None = None,
        short_pct: float | None = None,
        long1_pct: float | None = None,
        long2_pct: float | None = None,
    ) -> dict[str, Any]:
        if self._risk_locked:
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
        return {"ok": True, "locked": self._risk_locked}

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
        """Close one hedge leg only — does not flatten the rest of the pair."""
        sym = symbol.upper()
        ps = position_side.upper()
        if ps not in ("SHORT", "LONG"):
            return {"ok": False, "error": "invalid_position_side"}
        coin = self._coins.get(sym)
        pair_gate.begin_close(sym)
        t0 = time.perf_counter()
        try:
            if not hasattr(self._connector, "close_by_position_side"):
                return {"ok": False, "error": "close_by_position_side_unsupported"}
            r = self._connector.close_by_position_side(sym, ps, volume)
            if not r.get("ok"):
                return r
            if coin:
                coin.independent_legs_mode = True
                if ps == "SHORT":
                    coin.short = None
                    coin.status = (
                        STATUS_LONG2
                        if coin.long2
                        else STATUS_LONG1
                        if coin.long1
                        else STATUS_WATCHING
                    )
                else:
                    # Full LONG flatten — mark both recovery levels consumed this pair.
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
        Active pair = open primary long on exchange. Short1/Short2 are recovery legs while long lives.
        If the long is gone, flatten the full symbol — never leave orphan hedges.
        """
        sym = coin.symbol
        if getattr(self._connector.cfg, "paper", False):
            if not coin.long1 and (coin.long2 or coin.short):
                self._close_all(coin, "PAIR_NO_LONG1")
                return False
            return coin.long1 is not None or coin.long2 is not None or coin.short is not None

        has_long1 = self._exchange_has_long(sym)
        has_short = self._exchange_has_short(sym)

        if coin.long1 and not has_long1:
            log.info("scanner %s long1 closed on exchange — flattening full pair", sym)
            self._close_all(coin, "LONG1_GONE_EXCHANGE")
            return False

        if not has_long1 and (coin.long2 or coin.short) and not coin.independent_legs_mode:
            log.warning("scanner %s recovery legs without long1 — flattening full pair", sym)
            self._close_all(coin, "ORPHAN_RECOVERY")
            return False

        if not coin.long1 and not coin.long2 and not coin.short:
            return False

        return True

    def reconcile_from_exchange(self) -> dict[str, Any]:
        """Sync scanner state to Binance — flat symbols reset, open symbols kept."""
        open_syms = {str(p.get("symbol") or "").upper() for p in self._exchange_positions()}
        reset: list[str] = []
        for coin in self._coins.values():
            sym = coin.symbol
            if sym in open_syms:
                if (
                    not coin.independent_legs_mode
                    and not self._exchange_has_long(sym)
                    and (coin.long2 or coin.short or self._exchange_has_short(sym))
                ):
                    log.warning("reconcile %s flatten recovery legs without long1", sym)
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
        coin.recovery_peak_price = None
        coin.long1_opened_ms = 0
        coin.long2_opened_ms = 0
        coin.long1_adverse_peak_pct = 0.0
        coin.long2_adverse_peak_pct = 0.0
        coin.short_opened_ms = 0
        coin.short_adverse_peak_pct = 0.0
        coin.independent_legs_mode = False
        coin.status = STATUS_CLOSED
        coin.highest_price = None
        coin.qualifying_pct = 0.0
        coin.entry_signal_key = ""
        coin.unrealized_pnl = 0.0
        coin.retrace_pct = 0.0

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
                legs.append({"leg": "SHORT", "side": "SELL", "entry": coin.short.entry, "qty": coin.short.qty})
            if coin.long1:
                legs.append({"leg": "LONG1", "side": "BUY", "entry": coin.long1.entry, "qty": coin.long1.qty})
            if coin.long2:
                legs.append(
                    {
                        "leg": "LONG2",
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
        """Symbol with an open scanner strategy (short and/or recovery legs)."""
        for coin in self._coins.values():
            if coin.short or coin.long1 or coin.long2:
                return coin.symbol
            if coin.status in (STATUS_SHORT, STATUS_LONG1, STATUS_LONG2):
                return coin.symbol
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
            if coin.long1:
                continue
            if coin.status != STATUS_PENDING:
                continue
            self._demote_stale_pending(coin)
            if coin.status != STATUS_PENDING:
                continue
            if not self._retrace_entry_ok(coin):
                continue
            gain = max(coin.qualifying_pct or 0.0, self._entry_qualify_pct(coin))
            if gain < GAIN_THRESHOLD_PCT:
                continue
            if not self._live_entry_ok(coin):
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
            return
        candidates = self._pending_candidates()
        if not candidates:
            return
        self._try_open_long1_entry(candidates[0])

    def status(self) -> dict[str, Any]:
        active_sym = self._global_active_symbol()
        pending = self._pending_candidates()
        active = sum(1 for c in self._coins.values() if c.active() or c.status == STATUS_SHORT or c.long1 or c.long2)
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
            "long_pullback_pct": LONG_BOTH_PULLBACK_PCT,
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
        now_ms = int(ts_ms or time.time() * 1000)
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
                self._execute_pending_long1(coin)
            elif coin.status == STATUS_PENDING and self._entry_signal_ok(coin):
                self._execute_pending_long1(coin)

        if coin.short or coin.long1 or coin.long2:
            self._manage_positions(coin)

        if self._one_at_a_time and self._order_session_ok()[0] and not self._has_open_strategy():
            self._maybe_execute_best_pending()

        self._maybe_broadcast()

    def snapshot_rows(self) -> list[dict[str, Any]]:
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
                    STATUS_LONG1: 2,
                    STATUS_LONG2: 3,
                    STATUS_SHORT: 4,
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

    def _execute_pending_long1(self, coin: CoinStrategy) -> None:
        """Fire Long1 to Binance immediately when 15m-qualified retrace triggers."""
        sym = coin.symbol
        if not self._entry_signal_ok(coin):
            return
        ok, _ = self._order_session_ok()
        if not ok or sym in self._in_flight or coin.long1:
            return
        if self._one_at_a_time and self._has_open_strategy() and self._global_active_symbol() != sym:
            self._maybe_execute_best_pending()
            return
        self._try_open_long1_entry(coin)

    def _try_open_long1_entry(self, coin: CoinStrategy) -> None:
        sym = coin.symbol
        if not self._entry_signal_ok(coin):
            return
        if sym in self._in_flight:
            return
        if self._one_at_a_time:
            active = self._global_active_symbol()
            if active and active != sym:
                return
        if pair_gate.is_close_pending(sym):
            return
        ok_iso, _ = pair_gate.can_open(sym, self._global_active_symbol, self._exchange_positions)
        if not ok_iso:
            return
        if not getattr(self._connector.cfg, "paper", False):
            ok_hedge, hedge_err = self._connector.ensure_hedge_mode()
            if not ok_hedge:
                self._last_exec_error = f"{sym}: hedge_mode_required:{hedge_err}"
                log.warning("scanner LONG1 blocked %s: %s", sym, hedge_err)
                return
        self._in_flight.add(sym)
        try:
            entry = coin.price
            qty = self._qty_for(sym, entry, SHORT_LEVERAGE, self._short_pct)
            tp = entry * (1.0 + LONG_TP_PCT / 100.0)
            signal = ExecutionSignal(
                symbol=sym,
                side="BUY",
                quantity=qty,
                reference_price=entry,
                leverage=SHORT_LEVERAGE,
                magic=MAGIC_LONG1,
                leg="LONG1",
                tp=tp,
                signal_id=f"{sym}_LONG_{coin.entry_signal_key or coin.last_update_ms}",
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
                tp = fill * (1.0 + LONG_TP_PCT / 100.0)
                coin.long1 = LegPosition("BUY", fill, qty, SHORT_LEVERAGE, MAGIC_LONG1, tp)
                coin.status = STATUS_LONG1
                coin.long1_peak_price = fill
                coin.long1_adverse_peak_pct = 0.0
                coin.long2_adverse_peak_pct = 0.0
                self._mark_long1_opened(coin, sym)
                if hasattr(self._connector, "ensure_exchange_leverage"):
                    self._connector.ensure_exchange_leverage(sym)
                self._last_exec_error = None
                self._emit_signal(coin, "entered")
                log.info("scanner LONG %s qty=%s @ %s order=%s latency_ms=%s", sym, qty, fill, r.order_id, r.latency_ms)
            elif "duplicate" in str(r.error or "").lower():
                if not self._adopt_exchange_long1(coin, sym, qty, entry, tp):
                    self._last_exec_error = f"{sym}: duplicate_order_no_position"
                    coin.status = STATUS_PENDING
            else:
                err = str(r.error or "order_failed")
                self._last_exec_error = f"{sym}: {err}"
                log.warning("scanner LONG1 failed %s: %s latency_ms=%s", sym, err, r.latency_ms)
                coin.status = STATUS_PENDING
        finally:
            self._in_flight.discard(sym)

    def _try_open_short1(self, coin: CoinStrategy) -> None:
        sym = coin.symbol
        if not self._short1_entry_allowed(coin):
            return
        if sym in self._in_flight:
            return
        if pair_gate.is_close_pending(sym):
            return
        self._in_flight.add(sym)
        try:
            entry = coin.price
            qty = self._qty_for(sym, entry, LONG1_LEVERAGE, self._long1_pct)
            tp = entry * (1.0 - SHORT_TP_PCT / 100.0)
            signal = ExecutionSignal(
                symbol=sym,
                side="SELL",
                quantity=qty,
                reference_price=entry,
                leverage=LONG1_LEVERAGE,
                magic=MAGIC_SHORT,
                leg="LONG1",
                tp=tp,
                signal_id=f"{sym}_SHORT1_{coin.entry_signal_key or coin.last_update_ms}",
                signal_ts_ms=int(time.time() * 1000),
                partition_usd=self._partition_usd,
                partition_pct=self._long1_pct,
                margin_type="ISOLATED",
            )
            self._emit_signal(coin, "short1_executing")
            r = self._engine.execute(signal)
            self._last_exec_latency_ms = r.latency_ms or None
            if r.ok:
                fill = float(r.fill_price or entry)
                tp = fill * (1.0 - SHORT_TP_PCT / 100.0)
                coin.short = LegPosition("SELL", fill, qty, LONG1_LEVERAGE, MAGIC_SHORT, tp)
                coin.status = STATUS_SHORT
                coin.recovery_peak_price = fill
                self._mark_short_opened(coin, sym)
                if hasattr(self._connector, "ensure_exchange_leverage"):
                    self._connector.ensure_exchange_leverage(sym)
                self._last_exec_error = None
                self._emit_signal(coin, "short1_entered")
                log.info("scanner SHORT1 %s qty=%s @ %s order=%s latency_ms=%s", sym, qty, fill, r.order_id, r.latency_ms)
            elif "duplicate" in str(r.error or "").lower():
                if not self._adopt_exchange_short(coin, sym, qty, entry, tp):
                    self._last_exec_error = f"{sym}: duplicate_short1_no_position"
            else:
                err = str(r.error or "order_failed")
                self._last_exec_error = f"{sym} SHORT1: {err}"
                log.warning("scanner SHORT1 failed %s: %s latency_ms=%s", sym, err, r.latency_ms)
        finally:
            self._in_flight.discard(sym)

    def _try_open_short2(self, coin: CoinStrategy) -> None:
        sym = coin.symbol
        if not self._short2_entry_allowed(coin):
            return
        if sym in self._in_flight:
            return
        if pair_gate.is_close_pending(sym):
            return
        self._in_flight.add(sym)
        try:
            entry = coin.price
            qty = self._qty_for(sym, entry, LONG2_LEVERAGE, self._long2_pct)
            tp = entry * (1.0 - SHORT_TP_PCT / 100.0)
            signal = ExecutionSignal(
                symbol=sym,
                side="SELL",
                quantity=qty,
                reference_price=entry,
                leverage=LONG2_LEVERAGE,
                magic=MAGIC_LONG2,
                leg="LONG2",
                tp=tp,
                signal_id=f"{sym}_SHORT2_{coin.entry_signal_key or coin.last_update_ms}",
                signal_ts_ms=int(time.time() * 1000),
                partition_usd=self._partition_usd,
                partition_pct=self._long2_pct,
                margin_type="ISOLATED",
            )
            self._emit_signal(coin, "short2_executing")
            r = self._engine.execute(signal)
            self._last_exec_latency_ms = r.latency_ms or None
            if r.ok:
                fill = float(r.fill_price or entry)
                tp = fill * (1.0 - SHORT_TP_PCT / 100.0)
                coin.long2 = LegPosition("SELL", fill, qty, LONG2_LEVERAGE, MAGIC_LONG2, tp)
                coin.long2_peak_price = fill
                coin.status = STATUS_LONG2
                self._mark_long2_opened(coin)
                if hasattr(self._connector, "ensure_exchange_leverage"):
                    self._connector.ensure_exchange_leverage(sym)
                self._last_exec_error = None
                self._emit_signal(coin, "short2_entered")
                log.info("scanner SHORT2 %s qty=%s @ %s order=%s latency_ms=%s", sym, qty, fill, r.order_id, r.latency_ms)
            else:
                err = str(r.error or "order_failed")
                self._last_exec_error = f"{sym} SHORT2: {err}"
                log.warning("scanner SHORT2 failed %s: %s latency_ms=%s", sym, err, r.latency_ms)
        finally:
            self._in_flight.discard(sym)

    def _try_open_recovery_short(self, coin: CoinStrategy) -> None:
        if coin.short is None:
            self._try_open_short1(coin)
        else:
            self._try_open_short2(coin)

    def _try_open_short(self, coin: CoinStrategy) -> None:
        self._try_open_short1(coin)

    def _try_open_long(self, coin: CoinStrategy, leg: int) -> None:
        if leg == 2:
            self._try_open_short2(coin)

    def _leg_pnl(self, leg: LegPosition, price: float) -> float:
        if leg.side == "BUY":
            return (price - leg.entry) * leg.qty
        return (leg.entry - price) * leg.qty

    def _manage_positions(self, coin: CoinStrategy) -> None:
        if not self._ensure_pair_coherence(coin):
            return

        sym = coin.symbol
        if (coin.long1 or coin.short) and not getattr(self._connector.cfg, "paper", False):
            if hasattr(self._connector, "ensure_exchange_leverage"):
                self._connector.ensure_exchange_leverage(sym)

        price = coin.price
        if not coin.long1 and not coin.long2 and not coin.short:
            coin.unrealized_pnl = 0.0
            return

        long1_pnl = self._leg_pnl(coin.long1, price) if coin.long1 else 0.0
        long2_pnl = self._leg_pnl(coin.long2, price) if coin.long2 else 0.0
        short_pnl = self._leg_pnl(coin.short, price) if coin.short else 0.0
        coin.unrealized_pnl = long1_pnl + long2_pnl + short_pnl

        if SMART_EXIT_NET_PCT > 0 and self._partition_usd > 0:
            smart_target = self._partition_usd * SMART_EXIT_NET_PCT / 100.0
            if coin.unrealized_pnl >= smart_target:
                log.info(
                    "scanner %s SMART_EXIT pnl=%.4f target=%.4f",
                    sym,
                    coin.unrealized_pnl,
                    smart_target,
                )
                self._close_all(coin, "SMART_EXIT")
                return

        if coin.long1:
            adv1 = self._long_adverse_pct(coin, 1)
            if adv1 > coin.long1_adverse_peak_pct:
                coin.long1_adverse_peak_pct = adv1

        if coin.long1 and coin.short is None and self._short1_entry_allowed(coin):
            self._try_open_short1(coin)

        if coin.long1 and coin.short and coin.long2 is None and self._short2_entry_allowed(coin):
            self._try_open_short2(coin)

        # Primary long: TP at +2.5% or 0.5% retrace from its own peak.
        if coin.long1:
            if coin.long1.tp_price and price >= coin.long1.tp_price:
                self._close_leg(coin, "long1", reason="LONG_TP")
            elif coin.long1_peak_price is not None:
                if price > coin.long1_peak_price:
                    coin.long1_peak_price = price
                peak = coin.long1_peak_price
                if peak > 0:
                    pullback_pct = ((peak - price) / peak) * 100.0
                    if pullback_pct >= LONG_BOTH_PULLBACK_PCT:
                        log.info(
                            "scanner %s LONG_PULLBACK %.2f%% (peak=%s price=%s)",
                            coin.symbol,
                            pullback_pct,
                            peak,
                            price,
                        )
                        self._close_leg(coin, "long1", reason="LONG_PULLBACK")

        # Short1: TP at -2.5% or 0.5% bounce from trough.
        if coin.short:
            if coin.short.tp_price and price <= coin.short.tp_price:
                self._close_all(coin, "SHORT1_TP")
                return
            if coin.recovery_peak_price is not None:
                if price < coin.recovery_peak_price:
                    coin.recovery_peak_price = price
                trough = coin.recovery_peak_price
                if trough > 0:
                    bounce_pct = ((price - trough) / trough) * 100.0
                    if bounce_pct >= LONG_BOTH_PULLBACK_PCT:
                        log.info(
                            "scanner %s SHORT1_PULLBACK %.2f%% (trough=%s price=%s)",
                            coin.symbol,
                            bounce_pct,
                            trough,
                            price,
                        )
                        self._close_leg(coin, "short", reason="SHORT1_PULLBACK")

        # Short2: TP at -2.5% or 0.5% bounce from trough.
        if coin.long2 and coin.long2.side == "SELL":
            if coin.long2.tp_price and price <= coin.long2.tp_price:
                self._close_leg(coin, "long2", reason="SHORT2_TP")
            elif coin.long2_peak_price is not None:
                if price < coin.long2_peak_price:
                    coin.long2_peak_price = price
                trough = coin.long2_peak_price
                if trough > 0:
                    bounce_pct = ((price - trough) / trough) * 100.0
                    if bounce_pct >= LONG_BOTH_PULLBACK_PCT:
                        log.info(
                            "scanner %s SHORT2_PULLBACK %.2f%% (trough=%s price=%s)",
                            coin.symbol,
                            bounce_pct,
                            trough,
                            price,
                        )
                        self._close_leg(coin, "long2", reason="SHORT2_PULLBACK")

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
        pair_gate.begin_close(sym)
        try:
            if hasattr(self._connector, "close_by_position_side"):
                if leg.side == "BUY":
                    r = self._connector.close_by_position_side(sym, "LONG", leg.qty)
                else:
                    r = self._connector.close_by_position_side(sym, "SHORT", leg.qty)
            else:
                r = self._connector.close_leg(sym, leg.magic, leg.qty)
            if not r.get("ok"):
                log.warning("scanner close leg failed %s %s: %s", sym, leg_name, r.get("error") or r)
                return
            if leg_name == "long1":
                coin.long1 = None
                coin.long1_peak_price = None
                coin.long1_was_closed = True
                coin.status = STATUS_LONG2 if coin.long2 else (STATUS_SHORT if coin.short else STATUS_CLOSED)
            elif leg_name == "long2":
                coin.long2 = None
                coin.long2_peak_price = None
                coin.long2_was_closed = True
                coin.status = STATUS_LONG1 if coin.long1 else (STATUS_SHORT if coin.short else STATUS_CLOSED)
            elif leg_name == "short":
                coin.short = None
                coin.recovery_peak_price = None
                coin.short_was_closed = True
                coin.status = STATUS_LONG2 if coin.long2 else (STATUS_LONG1 if coin.long1 else STATUS_CLOSED)
            self._refresh_exchange_tps(coin)
            self._connector.invalidate_positions_cache()
            if reason:
                log.info("scanner closed leg %s %s reason=%s", sym, leg_name, reason)
        finally:
            pair_gate.end_close(sym)

    def _close_succeeded(self, close_result: dict[str, Any]) -> bool:
        if close_result.get("ok"):
            return True
        if close_result.get("note") == "already_flat":
            return True
        closed = close_result.get("closed")
        return isinstance(closed, list) and len(closed) > 0

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
                if coin.long1:
                    r = self._connector.close_leg(sym, coin.long1.magic, coin.long1.qty)
                    if r.get("ok"):
                        closed_legs.append({**r, "side": "BUY", "symbol": sym})
                    else:
                        all_ok = False
                if coin.long2:
                    r = self._connector.close_leg(sym, coin.long2.magic, coin.long2.qty)
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
            if self._close_succeeded(close_result):
                self._reset_coin_state(coin)
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
                log.warning(
                    "scanner close failed %s reason=%s err=%s — scanner state retained",
                    sym,
                    reason,
                    close_result.get("error") or close_result,
                )
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
