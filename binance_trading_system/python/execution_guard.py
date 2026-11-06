"""Protective infrastructure around execution. Holds no trading decisions.

CircuitBreaker pauses new primary entries while the exchange looks unreliable. It never closes
a position and never blocks exits or recovery hedges.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
from typing import Any

log = logging.getLogger("execution_guard")

BREAKER_THRESHOLD = 3
BREAKER_WINDOW_S = 300.0
BREAKER_OPEN_S = 120.0


class CircuitBreaker:
    """Opens after repeated failures on one channel, such as order outcomes or book reads."""

    def __init__(
        self,
        *,
        threshold: int = BREAKER_THRESHOLD,
        window_s: float = BREAKER_WINDOW_S,
        open_s: float = BREAKER_OPEN_S,
    ) -> None:
        self.threshold = threshold
        self.window_s = window_s
        self.open_s = open_s
        self._failures: dict[str, list[float]] = {}
        self._open_until = 0.0
        self._reason = ""
        self.trips = 0

    def record_failure(self, channel: str, detail: str = "") -> None:
        now = time.monotonic()
        rows = [t for t in self._failures.get(channel, []) if now - t <= self.window_s]
        rows.append(now)
        self._failures[channel] = rows
        if len(rows) >= self.threshold and now >= self._open_until:
            self._open_until = now + self.open_s
            self._reason = f"{channel}: {detail}"[:160]
            self.trips += 1
            # One more failure after the pause reopens it at once.
            self._failures[channel] = rows[-(self.threshold - 1):]
            log.error(
                "CIRCUIT_OPEN channel=%s failures=%s pause_s=%.0f detail=%s "
                "new entries paused, exits and reconcile keep running",
                channel, len(rows), self.open_s, detail[:120],
            )

    def record_success(self, channel: str) -> None:
        if self._failures.pop(channel, None) and not self.blocked():
            log.info("CIRCUIT_HEALTHY channel=%s", channel)

    def blocked(self) -> bool:
        return time.monotonic() < self._open_until

    def state(self) -> dict[str, Any]:
        left = max(0.0, self._open_until - time.monotonic())
        return {
            "state": "open" if left > 0 else "closed",
            "open_s_left": round(left, 1),
            "reason": self._reason if left > 0 else "",
            "trips": self.trips,
        }


def atomic_write_json(path: str, payload: Any) -> None:
    """Replace `path` in one step, so a crash cannot leave a truncated file."""
    folder = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class InstanceLock:
    """Exclusive OS lock, released by the kernel when the process dies, so it cannot go stale."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._fh: Any = None

    def acquire(self) -> bool:
        fh = open(self.path, "a+", encoding="utf-8")  # noqa: SIM115 - held for process lifetime
        try:
            if sys.platform == "win32":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None


def default_lock_path() -> str:
    explicit = (os.environ.get("BRIDGE_LOCK_FILE") or "").strip()
    if explicit:
        return explicit
    folder = "/var/lib/bilshenz"
    return os.path.join(folder if os.path.isdir(folder) else tempfile.gettempdir(), "bilshenz-bridge.lock")
