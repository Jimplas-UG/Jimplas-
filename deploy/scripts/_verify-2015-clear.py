#!/usr/bin/env python3
"""Confirm -2015 cleared: positions + user WS + no fresh rejects."""
from pathlib import Path
import paramiko
import time

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"

CMD = r'''
TOK=$(grep '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2- | tr -d '"' | tr -d "'")
sleep 3
curl -sS -m 5 http://127.0.0.1:8766/health > /tmp/h.json
curl -sS -m 10 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/positions > /tmp/p.json
curl -sS -m 10 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/status > /tmp/s.json
''' + PY + r''' -c "
import json
h=json.load(open('/tmp/h.json')); p=json.load(open('/tmp/p.json')); s=json.load(open('/tmp/s.json'))
sc=h.get('scanner') or {}
print('connected', h.get('connected'), 'can', sc.get('can_execute'), 'block', sc.get('exec_block'))
print('user_ws', (h.get('user_data_stream') or {}).get('ws_connected'), 'listen', (h.get('user_data_stream') or {}).get('listen_key_active'), 'err', (h.get('user_data_stream') or {}).get('last_error'))
print('positions', p.get('ok'), 'n', len(p.get('positions') or []), 'err', p.get('error'))
print('status connected', s.get('connected'), 'testnet', s.get('testnet'))
"
echo '=== fresh -2015 since login ==='
awk '$0 >= "2026-10-01T06:38:47"' /var/log/bilshenz/binance-api.log | grep -iE '2015|Invalid API-key|EXEC_FAIL' | tail -20 || echo NONE
'''

pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
_, o, e = c.exec_command(CMD, timeout=40)
print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
print(e.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii")[-800:])
c.close()
