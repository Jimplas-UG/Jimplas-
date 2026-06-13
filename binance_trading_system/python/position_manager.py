"""
Post-fill position manager — breakeven + trailing (tick-based).
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from binance_connector import BinanceConnector

log = logging.getLogger("position_manager")


class PositionManager:
    def __init__(self, connector: BinanceConnector, interval_sec: float = 2.0):
        self.connector = connector
        self.interval_sec = interval_sec
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._be_applied: set[str] = set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

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
        if self.connector.cfg.paper:
            return
        positions = self.connector.positions()
        if not positions:
            self._be_applied.clear()
            return
        tick_data = self.connector.tick()
        if not tick_data:
            return
        cfg = self.connector.cfg
        strategy_tick = cfg.pip_size
        for p in positions:
            sym = str(p.get("symbol", ""))
            side = p["type"]
            open_px = float(p["price_open"])
            vol = float(p["volume"])
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
