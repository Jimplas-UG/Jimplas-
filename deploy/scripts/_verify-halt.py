#!/usr/bin/env python3
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"

CMD = r"""
grep -E '^(SCANNER_EXEC|FORWARD_DRY_RUN)=' /etc/bilshenz.env
TOK=$(grep '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS -m 6 http://127.0.0.1:8766/health > /tmp/h.json
curl -sS -m 8 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/diagnostics > /tmp/d.json
curl -sS -m 8 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/positions > /tmp/p.json
""" + PY + r""" -c "
import json, time
t0=time.perf_counter()
h=json.load(open('/tmp/h.json'))
d=json.load(open('/tmp/d.json'))
p=json.load(open('/tmp/p.json'))
print('diag_rtt_ms', round((time.perf_counter()-t0)*1000,1))
sc=h.get('scanner') or {}
print('can_execute', sc.get('can_execute'), 'block', sc.get('exec_block'), 'exec_enabled', sc.get('exec_enabled'))
print('tick', (h.get('tick_stream') or {}).get('ws_connected'), 'scanner_ws', (h.get('scanner_stream') or {}).get('ws_connected'), 'user', (h.get('user_data_stream') or {}).get('ws_connected'))
print('diag_ok', d.get('ok'), 'diag_user_ws', (d.get('user_data_stream') or {}).get('ws_connected'), 'binance_ms', d.get('binance_latency_ms'))
pos=p.get('positions') if isinstance(p, dict) else p
print('open_n', len(pos) if isinstance(pos, list) else pos)
"
"""

pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
_, o, e = c.exec_command(CMD, timeout=40)
print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
print(e.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii")[-800:])
c.close()
