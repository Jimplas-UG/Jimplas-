#!/usr/bin/env python3
"""Pre-cash E2E audit — services, env, risk, positions, recent fails, latency."""
from __future__ import annotations

import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
set -a; . /etc/bilshenz.env; set +a
echo === GIT ===
cd /opt/bilshenz && git --no-pager log -1 --oneline && git status -sb
echo === SERVICES ===
systemctl is-active bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot 2>/dev/null
echo === ENV_KILL ===
grep -E '^(FORWARD_DRY_RUN|SCANNER_EXEC|SCANNER_ENABLED|SCANNER_ONE_TRADE|SCANNER_LONG_PULLBACK|SCANNER_SMART_EXIT|SCANNER_LONG1_PARTITION|SCANNER_LONG2_PARTITION|BINANCE_TESTNET|PAPER)=' /etc/bilshenz.env | sort
echo === RISK_JSON ===
cat /var/lib/bilshenz/scanner-risk.json 2>/dev/null || echo missing
echo === HEALTH ===
python3 - <<'PY'
import json,urllib.request,os,time
H={'Authorization':'Bearer '+os.environ.get('DESK_API_KEY','')}
BT=os.environ.get('BRIDGE_TOKEN') or os.environ.get('DESK_API_KEY') or ''
def get(url, headers=None, timeout=20):
  req=urllib.request.Request(url, headers=headers or {})
  with urllib.request.urlopen(req, timeout=timeout) as r:
    return json.loads(r.read().decode())
t0=time.time()
h=get('http://127.0.0.1:8766/health')
print('health_ms', round((time.time()-t0)*1000,1))
sc=h.get('scanner') or {}; ss=h.get('scanner_stream') or {}
print('connected', h.get('connected'), 'mode', h.get('mode'), 'ws', ss.get('ws_connected'), 'rest', ss.get('rest_active'), 'ticks', ss.get('ticks_received'), 'rest_ticks', ss.get('rest_ticks'))
if not h.get('connected'):
  print('WARN_NOT_CONNECTED — login with Futures API keys (testnet or mainnet; auto-detect enabled)')
print('can_execute', sc.get('can_execute'), 'block', sc.get('exec_block'), 'err', sc.get('last_exec_error'))
if (ss.get('ticks_received') or 0) <= 0:
  print('WARN_NO_TICKS_YET')
print('active', sc.get('active_symbol'), 'pending', sc.get('best_pending'))
print('risk', {k:sc.get(k) for k in ('partition_usd','short_partition_pct','long1_partition_pct','long2_partition_pct','long_pullback_pct','risk_locked','user_exec_halted','exec_enabled')})
# bridge auth health via token
pos=get('http://127.0.0.1:8766/api/positions', {'X-Bridge-Token':BT})
ps=pos.get('positions') or []
print('POSITIONS', len(ps))
for p in ps[:15]:
  print(' ', p.get('symbol'), p.get('positionSide') or p.get('type'), 'vol', p.get('volume'), 'lev', p.get('leverage'), 'xlev', p.get('exchange_leverage'), 'pnl', p.get('profit'))
# desk scanner
try:
  snap=get('http://127.0.0.1:8791/v1/binance/api/scanner/snapshot', H)
  print('BLOCKS', len(snap.get('blocks') or []))
  rows=[r for r in (snap.get('rows') or []) if r.get('status') not in ('Scanning', None)]
  print('ACTIVE_ROWS', len(rows))
  for r in rows[:8]:
    print(' ', r.get('symbol'), r.get('status'), '15m', r.get('pct15m'), 'retrace', r.get('retracePct'))
except Exception as e:
  print('desk_snap_err', e)
# diagnostics
try:
  d=get('http://127.0.0.1:8766/api/diagnostics', {'X-Bridge-Token':BT})
  print('diag_latency', d.get('binance_latency_ms'), 'recent', (d.get('execution') or {}).get('recent_latencies') or d.get('recent_latencies'))
except Exception as e:
  print('diag_err', e)
# calendar
try:
  cal=get('http://127.0.0.1:8766/api/trade-calendar?days=7', {'X-Bridge-Token':BT})
  print('CAL_7D', cal.get('total_pnl'), 'days', [(x.get('date'), x.get('pnl'), x.get('trades')) for x in (cal.get('days') or [])[-7:]])
except Exception as e:
  print('cal_err', e)
PY
echo === FAIL_LOGS ===
journalctl -u bilshenz-binance-api -n 120 --no-pager 2>/dev/null | tr -cd '\11\12\15\40-\176' | grep -E 'EXEC_FAIL|ERROR|OOM|Traceback|hedge|orphan|insufficient|duplicate|SMART_EXIT|LONG_PULLBACK|ORPHAN|blocked' | tail -n 40
echo === MEM ===
free -h | head -2
ps -o pid,rss,cmd -C python3 2>/dev/null | head -10 || true
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
