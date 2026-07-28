#!/usr/bin/env python3
"""Audit whether bilshenz-forward-bot is executing as intended."""
from __future__ import annotations

import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
set -a; . /etc/bilshenz.env; set +a
python3 - <<'PY'
import json, os, subprocess, urllib.request, time

def sh(cmd):
    return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.STDOUT, errors='replace')

def get(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())

print('=== SERVICES ===')
print(sh('systemctl is-active bilshenz-forward-bot bilshenz-binance-api bilshenz-desk-api 2>/dev/null || true').strip())
print('=== UNIT ===')
print(sh('systemctl cat bilshenz-forward-bot 2>/dev/null | tr -cd "\\11\\12\\15\\40-\\176" | head -60').strip())
print('=== ENV ===')
print(sh("grep -E '^(FORWARD_|SCANNER_|BINANCE_TESTNET|BINANCE_PAPER|MT5_|BRIDGE_|DESK_)' /etc/bilshenz.env 2>/dev/null | sed -E 's/(KEY|SECRET|TOKEN|PASSWORD)=.*/\\1=***/' | sort").strip())
print('=== TRADINGBOT ENV ===')
print(sh("grep -E '^(FORWARD_|SCANNER_|BINANCE_|BRIDGE_|DESK_|MT5_)' /etc/tradingbot.env 2>/dev/null | sed -E 's/(KEY|SECRET|TOKEN|PASSWORD)=.*/\\1=***/' | sort || echo missing").strip())
print('=== GIT ===')
print(sh('cd /opt/bilshenz && git log -1 --oneline').strip())
print('=== PROCESS ===')
print(sh("ps -eo pid,etime,rss,cmd | grep -E 'forward|run-forward' | grep -v grep | head -10 || true").strip())
print('=== FORWARD LOG TAIL ===')
for path in ('/var/log/tradingbot/forward-bot.log','/var/log/bilshenz/forward-bot.log'):
    if os.path.isfile(path):
        print('LOG', path)
        print(sh(f"tail -n 60 {path} | tr -cd '\\11\\12\\15\\40-\\176'"))
        break
else:
    print('NO_FORWARD_LOG_FILE')
print('=== JOURNAL ===')
print(sh("journalctl -u bilshenz-forward-bot -n 50 --no-pager 2>/dev/null | tr -cd '\\11\\12\\15\\40-\\176' | tail -n 50").strip())
print('=== HEALTH BRIDGE ===')
try:
    h=get('http://127.0.0.1:8766/health')
    sc=h.get('scanner') or {}
    print('mode', h.get('mode'), 'connected', h.get('connected'), 'can_execute', sc.get('can_execute'), 'block', sc.get('exec_block'), 'active', sc.get('active_symbol'), 'err', sc.get('last_exec_error'))
    print('risk', {k:sc.get(k) for k in ('partition_usd','short_partition_pct','long1_partition_pct','long2_partition_pct','long_pullback_pct','exec_enabled','risk_locked')})
except Exception as e:
    print('health_err', e)
BT=os.environ.get('BRIDGE_TOKEN') or os.environ.get('DESK_API_KEY') or ''
try:
    pos=get('http://127.0.0.1:8766/api/positions', {'X-Bridge-Token':BT})
    ps=pos.get('positions') or []
    print('POSITIONS', len(ps))
    for p in ps[:10]:
        print(' ', p.get('symbol'), p.get('positionSide') or p.get('type'), 'vol', p.get('volume'), 'pnl', p.get('profit'))
except Exception as e:
    print('pos_err', e)
try:
    d=get('http://127.0.0.1:8766/api/diagnostics', {'X-Bridge-Token':BT})
    print('diag_latency', d.get('binance_latency_ms'))
    recent=(d.get('execution') or {}).get('recent_latencies') or d.get('recent_latencies') or []
    print('recent_exec', recent[:8])
except Exception as e:
    print('diag_err', e)
print('=== DESK HEALTH ===')
try:
    print(get('http://127.0.0.1:8791/health'))
except Exception as e:
    print('desk_err', e)
PY
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=120)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[:3000])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
