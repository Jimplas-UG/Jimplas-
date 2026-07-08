"""
Tick-by-tick multi-coin momentum scanner + retracement short strategy.

Monitors 1m / 3m / 5m / 15m rolling % on every price tick (max study window 15m).
Entry: tick move >= 5% gain, then >= 0.7% retrace from peak → short (50% partition).
Recovery: +2% adverse from short → Long1 (40%); +4% → Long2 (40%).
Each long closes on 0.5% retrace from its own peak.
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("momentum_scanner")

GAIN_THRESHOLD_PCT = float(os.environ.get("SCANNER_GAIN_PCT", "5.0"))
RETRACE_ENTRY_PCT = float(os.environ.get("SCANNER_RETRACE_PCT", "0.7"))
SHORT_TP_PCT = float(os.environ.get("SCANNER_SHORT_TP_PCT", "2.5"))
LONG1_ADVERSE_PCT = float(os.environ.get("SCANNER_LONG1_PCT", "2.0"))
LONG2_ADVERSE_PCT = float(os.environ.get("SCANNER_LONG2_PCT", "4.0"))
LONG_TP_PCT = float(os.environ.get("SCANNER_LONG_TP_PCT", "2.5"))
LONG_BOTH_PULLBACK_PCT = float(os.environ.get("SCANNER_LONG_PULLBACK_PCT", "0.5"))
SMART_EXIT_NET_PCT = float(os.environ.get("SCANNER_SMART_EXIT_PCT", "1.0"))
SHORT_LEVERAGE = int(os.environ.get("SCANNER_SHORT_LEV", "5"))
LONG1_LEVERAGE = int(os.environ.get("SCANNER_LONG1_LEV", "10"))
LONG2_LEVERAGE = int(os.environ.get("SCANNER_LONG2_LEV", "10"))
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
SIGNAL_WINDOW_SEC = {f"{m}m": m * 60 for m in TIMEFRAMES_MIN}

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
    """Server env kill-switches — only way to halt scanner orders (not the mobile app)."""
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
    long1_peak_price: float | None = None
    long2_peak_price: float | None = None
    recovery_peak_price: float | None = None
    unrealized_pnl: float = 0.0
    last_update_ms: int = 0
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
        self._recent_signals: deque[dict[str, Any]] = deque(maxlen=48)
        self._last_exec_error: str | None = None
        self._session_ok_cache: tuple[float, tuple[bool, str]] | None = None
        self._tf_emit_times: dict[str, deque[float]] = {
            f"{m}m": deque(maxlen=SIGNALS_PER_TF + 2) for m in TIMEFRAMES_MIN
        }

    def set_exec_enabled(self, enabled: bool) -> None:
        """No-op — execution is armed on Binance connect; halt via SCANNER_EXEC or FORWARD_DRY_RUN env."""
        can_exec, block = self._order_session_ok()
        log.info(
            "scanner set_exec_enabled(%s) ignored (env_controlled) can_execute=%s block=%s",
            enabled,
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
        else:
            result = self._session_connected()
        self._session_ok_cache = (now, result)
        return result

    def set_risk_config(
        self,
        partition_usd: float | None = None,
        short_pct: float | None = None,
        long1_pct: float | None = None,
        long2_pct: float | None = None,
    ) -> None:
        if partition_usd is not None and partition_usd > 0:
            self._partition_usd = float(partition_usd)
        if short_pct is not None:
            self._short_pct = max(1.0, min(100.0, float(short_pct)))
        if long1_pct is not None:
            self._long1_pct = max(1.0, min(100.0, float(long1_pct)))
        if long2_pct is not None:
            self._long2_pct = max(1.0, min(100.0, float(long2_pct)))
        log.info(
            "scanner risk partition=$%s short=%s%% long1=%s%% long2=%s%%",
            self._partition_usd,
            self._short_pct,
            self._long1_pct,
            self._long2_pct,
        )

    def close_strategy(self, symbol: str) -> dict[str, Any]:
        sym = symbol.upper()
        coin = self._coins.get(sym)
        if not coin:
            return {"ok": False, "error": "unknown_symbol"}
        if coin.short or coin.long1 or coin.long2:
            self._close_all(coin, "MANUAL_APP")
            return {"ok": True, "closed": sym}
        if coin.status == STATUS_PENDING:
            coin.status = STATUS_WATCHING
            return {"ok": True, "cancelled_pending": sym}
        return {"ok": False, "error": "nothing_to_close"}

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
                legs.append({"leg": "LONG2", "side": "BUY", "entry": coin.long2.entry, "qty": coin.long2.qty})
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
            if coin.short:
                continue
            if coin.status != STATUS_PENDING:
                continue
            if coin.retrace_pct < RETRACE_ENTRY_PCT:
                continue
            gain = max(coin.qualifying_pct or 0.0, coin.best_pct)
            if gain < GAIN_THRESHOLD_PCT:
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
            if reason not in ("SCANNER_EXEC=0", "FORWARD_DRY_RUN"):
                self._last_exec_error = reason
            return
        if self._one_at_a_time and self._has_open_strategy():
            return
        candidates = self._pending_candidates()
        if not candidates:
            return
        self._try_open_short(candidates[0])

    def status(self) -> dict[str, Any]:
        active_sym = self._global_active_symbol()
        pending = self._pending_candidates()
        active = sum(1 for c in self._coins.values() if c.active() or c.status == STATUS_SHORT or c.long1 or c.long2)
        can_exec, block_reason = self._order_session_ok()
        return {
            "enabled": self._enabled,
            "exec_enabled": can_exec,
            "can_execute": can_exec,
            "exec_block": block_reason or None,
            "exec_env_controlled": True,
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

        if coin.status in (STATUS_SCANNING, STATUS_CLOSED):
            if coin.best_pct >= GAIN_THRESHOLD_PCT:
                coin.status = STATUS_WATCHING
                coin.highest_price = price
                coin.retrace_pct = 0.0
                coin.qualifying_pct = max(coin.qualifying_pct or 0.0, coin.best_pct)
                self._emit_signal(coin, "watch")
        elif coin.status in (STATUS_WATCHING, STATUS_PENDING):
            coin.qualifying_pct = max(coin.qualifying_pct or 0.0, coin.best_pct)
            if coin.highest_price is None or price > coin.highest_price:
                coin.highest_price = price
            if coin.highest_price and coin.highest_price > 0:
                coin.retrace_pct = ((coin.highest_price - price) / coin.highest_price) * 100.0
            if coin.status == STATUS_PENDING and coin.retrace_pct < RETRACE_ENTRY_PCT:
                coin.status = STATUS_WATCHING
            elif coin.retrace_pct >= RETRACE_ENTRY_PCT and coin.status != STATUS_PENDING:
                coin.status = STATUS_PENDING
                self._emit_signal(coin, "pending")
                if self._order_session_ok()[0] and sym not in self._in_flight and not coin.short:
                    if self._one_at_a_time:
                        self._maybe_execute_best_pending()
                    else:
                        self._try_open_short(coin)
            elif (
                coin.status == STATUS_PENDING
                and self._order_session_ok()[0]
                and self._one_at_a_time
                and sym not in self._in_flight
                and not coin.short
                and not self._has_open_strategy()
            ):
                self._maybe_execute_best_pending()

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
            coin.pct_3m, coin.pct_5m, coin.pct_15m = self._rolling_pcts(coin, now_ms)
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

    def _try_open_short(self, coin: CoinStrategy) -> None:
        sym = coin.symbol
        if sym in self._in_flight:
            return
        if self._one_at_a_time:
            active = self._global_active_symbol()
            if active and active != sym:
                return
        self._in_flight.add(sym)
        try:
            entry = coin.price
            qty = self._qty_for(sym, entry, SHORT_LEVERAGE, self._short_pct)
            tp = entry * (1.0 - SHORT_TP_PCT / 100.0)
            r = self._connector.order_market_leg(
                sym,
                "SELL",
                qty,
                sl=None,
                tp=tp,
                leverage=SHORT_LEVERAGE,
                magic=MAGIC_SHORT,
                leg="SHORT",
            )
            if r.get("ok"):
                fill = float(r.get("fill_price") or entry)
                coin.short = LegPosition("SELL", fill, qty, SHORT_LEVERAGE, MAGIC_SHORT, tp)
                coin.status = STATUS_SHORT
                coin.long1_was_closed = False
                coin.long1_peak_price = None
                coin.long2_peak_price = None
                coin.recovery_peak_price = None
                self._last_exec_error = None
                self._emit_signal(coin, "entered")
                log.info("scanner SHORT %s qty=%s @ %s", sym, qty, fill)
            else:
                err = str(r.get("error") or "order_failed")
                self._last_exec_error = f"{sym}: {err}"
                log.warning("scanner SHORT failed %s: %s", sym, err)
                # Keep pending so the next tick / queue pass can retry (e.g. margin, tick, rate limit).
                coin.status = STATUS_PENDING
        finally:
            self._in_flight.discard(sym)

    def _try_open_long(self, coin: CoinStrategy, leg: int) -> None:
        sym = coin.symbol
        if sym in self._in_flight:
            return
        self._in_flight.add(sym)
        try:
            entry = coin.price
            lev = LONG1_LEVERAGE if leg == 1 else LONG2_LEVERAGE
            magic = MAGIC_LONG1 if leg == 1 else MAGIC_LONG2
            leg_pct = self._long1_pct if leg == 1 else self._long2_pct
            qty = self._qty_for(sym, entry, lev, leg_pct)
            r = self._connector.order_market_leg(
                sym, "BUY", qty, sl=None, tp=None, leverage=lev, magic=magic, leg=f"LONG{leg}"
            )
            if r.get("ok"):
                fill = float(r.get("fill_price") or entry)
                pos = LegPosition("BUY", fill, qty, lev, magic, None)
                if leg == 1:
                    coin.long1 = pos
                    coin.long1_peak_price = fill
                    coin.status = STATUS_LONG1
                else:
                    coin.long2 = pos
                    coin.long2_peak_price = fill
                    coin.status = STATUS_LONG2
                self._last_exec_error = None
                self._emit_signal(coin, f"long{leg}_entered")
                log.info("scanner LONG%d %s qty=%s @ %s", leg, sym, qty, fill)
            else:
                err = str(r.get("error") or "order_failed")
                self._last_exec_error = f"{sym} LONG{leg}: {err}"
                log.warning("scanner LONG%d failed %s: %s", leg, sym, err)
        finally:
            self._in_flight.discard(sym)

    def _leg_pnl(self, leg: LegPosition, price: float) -> float:
        if leg.side == "BUY":
            return (price - leg.entry) * leg.qty
        return (leg.entry - price) * leg.qty

    def _manage_positions(self, coin: CoinStrategy) -> None:
        price = coin.price
        short = coin.short
        if not short:
            coin.unrealized_pnl = 0.0
            return

        short_pnl = self._leg_pnl(short, price)
        long1_pnl = self._leg_pnl(coin.long1, price) if coin.long1 else 0.0
        long2_pnl = self._leg_pnl(coin.long2, price) if coin.long2 else 0.0
        coin.unrealized_pnl = short_pnl + long1_pnl + long2_pnl

        adverse_pct = ((price - short.entry) / short.entry) * 100.0 if short.entry > 0 else 0.0

        # Long1 @ +2% adverse; Long2 @ +4% from short entry (independent triggers).
        if coin.long1 is None and adverse_pct >= LONG1_ADVERSE_PCT:
            self._try_open_long(coin, 1)
        if coin.long2 is None and adverse_pct >= LONG2_ADVERSE_PCT:
            self._try_open_long(coin, 2)

        # Long1: close on 0.5% retrace from its own peak.
        if coin.long1 and coin.long1_peak_price is not None:
            if price > coin.long1_peak_price:
                coin.long1_peak_price = price
            peak = coin.long1_peak_price
            if peak > 0:
                pullback_pct = ((peak - price) / peak) * 100.0
                if pullback_pct >= LONG_BOTH_PULLBACK_PCT:
                    log.info(
                        "scanner %s LONG1_PULLBACK %.2f%% (peak=%s price=%s)",
                        coin.symbol,
                        pullback_pct,
                        peak,
                        price,
                    )
                    self._close_leg(coin, "long1", reason="LONG1_PULLBACK")

        # Long2: close immediately on 0.5% retrace from its own peak.
        if coin.long2 and coin.long2_peak_price is not None:
            if price > coin.long2_peak_price:
                coin.long2_peak_price = price
            peak = coin.long2_peak_price
            if peak > 0:
                pullback_pct = ((peak - price) / peak) * 100.0
                if pullback_pct >= LONG_BOTH_PULLBACK_PCT:
                    log.info(
                        "scanner %s LONG2_PULLBACK %.2f%% (peak=%s price=%s)",
                        coin.symbol,
                        pullback_pct,
                        peak,
                        price,
                    )
                    self._close_leg(coin, "long2", reason="LONG2_PULLBACK")

        if short.tp_price and price <= short.tp_price:
            self._close_all(coin, "SHORT_TP")
            return

    def _close_leg(self, coin: CoinStrategy, leg_name: str, reason: str = "") -> None:
        sym = coin.symbol
        leg = coin.long1 if leg_name == "long1" else coin.long2 if leg_name == "long2" else None
        if not leg:
            return
        self._connector.close_leg(sym, leg.magic, leg.qty)
        if leg_name == "long1":
            coin.long1 = None
            coin.long1_peak_price = None
            coin.long1_was_closed = True
            coin.status = STATUS_SHORT if coin.short else STATUS_CLOSED
        elif leg_name == "long2":
            coin.long2 = None
            coin.long2_peak_price = None
            coin.status = STATUS_LONG1 if coin.long1 else (STATUS_SHORT if coin.short else STATUS_CLOSED)
        if reason:
            log.info("scanner closed leg %s %s reason=%s", sym, leg_name, reason)

    def _close_all(self, coin: CoinStrategy, reason: str) -> None:
        sym = coin.symbol
        if coin.short:
            self._connector.close_leg(sym, coin.short.magic, coin.short.qty)
        if coin.long1:
            self._connector.close_leg(sym, coin.long1.magic, coin.long1.qty)
        if coin.long2:
            self._connector.close_leg(sym, coin.long2.magic, coin.long2.qty)
        coin.short = None
        coin.long1 = None
        coin.long2 = None
        coin.long1_was_closed = False
        coin.long1_peak_price = None
        coin.long2_peak_price = None
        coin.recovery_peak_price = None
        coin.status = STATUS_CLOSED
        coin.highest_price = None
        coin.qualifying_pct = 0.0
        coin.unrealized_pnl = 0.0
        log.info("scanner closed %s reason=%s", sym, reason)
        self._bump_trades_closed()
        if self._one_at_a_time:
            self._maybe_execute_best_pending()

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
