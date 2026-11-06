#!/usr/bin/env python3
"""Restart the bridge only when it is hung. Runs from a systemd timer, once per check.

systemd already restarts a crashed process, so this covers what it cannot see: a live process
whose scanner has stopped receiving ticks. A restart is safe for open positions because the
bridge adopts them from the exchange at startup, and it never closes anything itself.

It holds rather than restarts when:
  * the service is stopped, because an operator stopped it, so it must stay stopped
  * Binance has paused REST, because a restart cannot help and more calls extend a ban
  * the bridge restarted within the grace period, so it is still recovering
  * the hourly restart budget is spent, so a persistent fault cannot cause a restart loop
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from typing import Any

SERVICE = "bilshenz-binance-api"
HEALTH_URL = os.environ.get("WATCHDOG_HEALTH_URL", "http://127.0.0.1:8766/health")
STATE_FILE = os.environ.get("WATCHDOG_STATE_FILE", "/var/lib/bilshenz/watchdog-state.json")
LOG_FILE = os.environ.get("WATCHDOG_LOG_FILE", "/var/log/bilshenz/watchdog.log")
PROC_PATTERN = "binance_trading_system/python/.venv/bin/python main.py"
STALL_S = 180.0
FAILS_TO_RESTART = 3
GRACE_S = 300.0
MAX_RESTARTS_PER_HOUR = 3


def decide(
    state: dict[str, Any],
    health: dict[str, Any] | None,
    *,
    now: float,
    service_active: bool,
    workers: int,
) -> tuple[str, str]:
    """Returns (action, reason). Action is ok, hold, alert or restart. Updates state in place."""
    restarts = [t for t in state.get("restarts", []) if now - t < 3600]
    state["restarts"] = restarts
    if workers > 1:
        state["fails"] = 0
        return "alert", f"duplicate_workers:{workers}"
    if not service_active:
        state["fails"] = 0
        return "hold", "service_stopped"
    if restarts and now - restarts[-1] < GRACE_S:
        state["fails"] = 0
        return "hold", "recovering_after_restart"
    if health is not None and float(health.get("rest_cool_s") or 0) > 0:
        state["fails"] = 0
        return "hold", "binance_rest_paused"
    problem = ""
    if health is None:
        problem = "health_unreachable"
    else:
        scanner = health.get("scanner") or {}
        age = scanner.get("last_tick_age_s")
        if age is not None and float(age) > STALL_S:
            problem = f"no_ticks_for_{float(age):.0f}s"
    if not problem:
        state["fails"] = 0
        return "ok", "healthy"
    state["fails"] = int(state.get("fails") or 0) + 1
    if state["fails"] < FAILS_TO_RESTART:
        return "hold", f"{problem}:strike_{state['fails']}"
    if len(restarts) >= MAX_RESTARTS_PER_HOUR:
        return "alert", f"{problem}:restart_budget_spent"
    state["fails"] = 0
    state["restarts"] = restarts + [now]
    return "restart", problem


def probe() -> dict[str, Any] | None:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None


def main() -> int:
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        state = {}
    active = subprocess.run(["systemctl", "is-active", "--quiet", SERVICE], check=False).returncode == 0
    pg = subprocess.run(["pgrep", "-fc", PROC_PATTERN], capture_output=True, text=True, check=False)
    workers = int(pg.stdout.strip() or 0)
    action, reason = decide(state, probe() if active else None, now=time.time(), service_active=active, workers=workers)
    if action == "restart":
        subprocess.run(["systemctl", "restart", SERVICE], check=False)
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh)
    os.replace(tmp, STATE_FILE)
    if action != "ok":
        stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp} WATCHDOG action={action} reason={reason}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
