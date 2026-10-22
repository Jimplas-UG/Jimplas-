"""
Post-fill position manager — legacy pip BE + trailing.

Sep premium desk: short_first_v1 owns exits (TP / pullback / rescue / invalidation /
SMART_EXIT). The old 2s REST bookTicker loop was the #1 FRA weight burner and fed
the Oct 418 → false SHORT_GONE storm. Default is idle unless explicitly enabled.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binance_connector import BinanceConnector

log = logging.getLogger("position_manager")


def _env_enabled(name: str, default: str = "0") -> bool:
    return str(os.environ.get(name, default) or default).strip().lower() in ("1", "true", "yes", "on")


class PositionManager:
    def __init__(self, connector: BinanceConnector, interval_sec: float = 15.0):
        self.connector = connector
        # Was 2.0s — too hot for futures IP weight. Floor 15s even if enabled.
        self.interval_sec = max(15.0, float(interval_sec))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._be_applied: set[str] = set()
        self.enabled = _env_enabled("POSITION_MANAGER_ENABLED", "0")

    def start(self) -> None:
        if not self.enabled:
            log.info(
                "position_manager idle — short_first owns exits "
                "(set POSITION_MANAGER_ENABLED=1 only for legacy pip BE/trail)"
            )
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.warning("position_manager ENABLED interval=%.0fs — burns REST if WS missing", self.interval_sec)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._tick()
            except Exception as e:
                log.error("position_manager tick: %s", e)
            self._stop.wait(self.interval_sec)

    def _tick(self) -> None:
        if not self.enabled:
            return
        if self.connector.cfg.paper:
            return
        # Never compete with scanner / cool for IP weight.
        if getattr(self.connector, "rest_cooling_left", lambda: 0.0)() > 0.05:
            return
        pause = getattr(self.connector, "_weight_pause_left", None)
        if callable(pause) and float(pause() or 0.0) > 0.05:
            return
        # Cache-only book — never force REST.
        positions = self.connector.positions(force=False)
        if not positions:
            self._be_applied.clear()
            return
        cfg = self.connector.cfg
        strategy_tick = cfg.pip_size
        for p in positions:
            sym = str(p.get("symbol", "") or "").upper()
            if not sym:
                continue
            side = p["type"]
            open_px = float(p["price_open"])
            vol = float(p["volume"])
            # Prefer mark already on the position row / cached book — no fresh REST.
            price = float(p.get("price_current") or p.get("markPrice") or 0)
            if price <= 0:
                tick_data = self.connector.tick(sym)
                if not tick_data:
                    continue
                price = tick_data["bid"] if side == "BUY" else tick_data["ask"]
            profit_ticks = (
                (price - open_px) / strategy_tick
                if side == "BUY"
                else (open_px - price) / strategy_tick
            )
            pos_key = f"{sym}:{side}:{open_px}"
            if profit_ticks >= cfg.be_trigger_pips and pos_key not in self._be_applied:
                be = open_px + ((1 if side == "BUY" else -1) * cfg.be_offset_pips * strategy_tick)
                if self.connector.modify_stop(side, be, vol):
                    self._be_applied.add(pos_key)
            if profit_ticks >= cfg.trail_start_pips:
                step = cfg.trail_step_pips * strategy_tick
                nsl = price - step if side == "BUY" else price + step
                self.connector.modify_stop(side, nsl, vol)
