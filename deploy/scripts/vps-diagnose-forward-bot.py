#!/usr/bin/env python3
"""Diagnose bilshenz-forward-bot on VPS."""
from __future__ import annotations

import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
set -e
echo === SERVICES ===
systemctl is-active bilshenz-forward-bot bilshenz-binance-api bilshenz-desk-api bilshenz-watchdog 2>/dev/null || true
echo
systemctl status bilshenz-forward-bot --no-pager -l 2>&1 | head -n 40
echo
echo === ENV ===
grep -E '^(FORWARD_|SCANNER_EXEC|SCANNER_ENABLED|FORWARD_DRY_RUN|BINANCE_|BRIDGE_)' /etc/bilshenz.env 2>/dev/null | sed -E 's/(SECRET|KEY|TOKEN|PASSWORD)=.*/\1=***/' | sort
echo
echo === UNIT ===
systemctl cat bilshenz-forward-bot 2>&1 | head -n 60
echo
echo === LOG_TAIL ===
tail -n 80 /var/log/tradingbot/forward-bot.log 2>/dev/null || echo NO_tradingbot_forward_log
echo ---
tail -n 40 /var/log/bilshenz/forward-bot.log 2>/dev/null || echo NO_bilshenz_forward_log
echo
echo === JOURNAL ===
journalctl -u bilshenz-forward-bot -n 50 --no-pager 2>&1 | tail -n 50
echo
echo === PROCESS ===
ps aux | grep -E 'forward|Forward' | grep -v grep || echo no_forward_process
echo
echo === HEALTH ===
curl -sS http://127.0.0.1:8766/health | python3 -c 'import sys,json; h=json.load(sys.stdin); s=h.get("scanner") or {}; print({k:s.get(k) for k in ("can_execute","exec_block","active_symbol","pending_count","exec_enabled","user_exec_halted")}); print("connected", h.get("connected"), "mode", h.get("mode"))'
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
