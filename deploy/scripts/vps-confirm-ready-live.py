#!/usr/bin/env python3
"""Confirm FRA live stack is armed and waiting for entries."""
from __future__ import annotations

from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"

CMD = r'''
set +e
echo '=== services ==='
systemctl is-active bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot
echo '=== env ==='
grep -E '^(BINANCE_TESTNET|BINANCE_FORCE_|BINANCE_PAPER|SCANNER_EXEC|SCANNER_ENABLED|FORWARD_DRY_RUN|TRADE_HISTORY_SINCE|STRATEGY_FREEZE)=' /etc/bilshenz.env
python3 - <<'PY'
from pathlib import Path
raw=Path('/etc/bilshenz.env').read_text()
for ln in raw.splitlines():
    if not ln or '=' not in ln: continue
    k,v=ln.split('=',1); k=k.strip(); v=v.strip().strip('"').strip("'")
    if k in ('BINANCE_API_KEY','BINANCE_API_SECRET','BRIDGE_TOKEN','SESSION_ENC_KEY'):
        print(f'{k} len={len(v)} ok={len(v)>8}')
print('env_lines', len(raw.splitlines()), 'newlines', raw.count(chr(10)))
PY
TOK=$(grep '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS -m 6 http://127.0.0.1:8766/health > /tmp/h.json
curl -sS -m 8 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/diagnostics > /tmp/d.json
curl -sS -m 8 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/positions > /tmp/p.json
curl -sS -m 8 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/status > /tmp/s.json
curl -sS -m 4 http://127.0.0.1:8791/health > /tmp/desk.json 2>/dev/null
''' + PY + r''' <<'PY'
import json
h=json.load(open('/tmp/h.json'))
d=json.load(open('/tmp/d.json'))
p=json.load(open('/tmp/p.json'))
s=json.load(open('/tmp/s.json'))
try:
  desk=json.load(open('/tmp/desk.json'))
except Exception:
  desk={}
sc=h.get('scanner') or {}
print('=== bridge ===')
print('connected', h.get('connected'), 'status_testnet', s.get('testnet'), 'cool', h.get('rest_cool_s'))
print('can_execute', sc.get('can_execute'), 'exec_enabled', sc.get('exec_enabled'), 'block', sc.get('exec_block'))
print('partition_usd', sc.get('partition_usd'), 'strategy', sc.get('strategy_id'), sc.get('strategy_name'))
print('active_symbol', sc.get('active_symbol'), 'pending', sc.get('pending_count'), 'tracked', sc.get('symbols_tracked'))
print('trades_closed_today', sc.get('trades_closed_today'))
print('tick_ws', (h.get('tick_stream') or {}).get('ws_connected'),
      'scanner_ws', (h.get('scanner_stream') or {}).get('ws_connected'),
      'rest_active', (h.get('scanner_stream') or {}).get('rest_active'),
      'user_ws', (h.get('user_data_stream') or {}).get('ws_connected'),
      'listen', (h.get('user_data_stream') or {}).get('listen_key_active'))
print('diag_ok', d.get('ok'), 'binance_ms', d.get('binance_latency_ms'), 'cpu', d.get('cpu_pct'))
print('open_positions', len(p.get('positions') or []), 'pos_ok', p.get('ok'), 'pos_err', p.get('error'))
print('desk', desk)
# ready verdict
ok = (
  h.get('connected') is True
  and sc.get('can_execute') is True
  and sc.get('exec_block') in (None, '')
  and (h.get('scanner_stream') or {}).get('ws_connected')
  and (h.get('user_data_stream') or {}).get('ws_connected')
  and p.get('ok') is True
)
print('READY_FOR_ENTRIES' if ok else 'NOT_READY')
PY
echo '=== forward-bot recent ==='
journalctl -u bilshenz-forward-bot --since '10 min ago' --no-pager | tail -25
echo '=== api recent exec/errors ==='
grep -iE 'EXEC_|scanner SHORT|scanner LONG|2015|Invalid API|login ok|LIVE' /var/log/bilshenz/binance-api.log | tail -20
'''

def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print(err.encode("ascii", "replace").decode("ascii")[-1500:])
    c.close()

if __name__ == "__main__":
    main()
