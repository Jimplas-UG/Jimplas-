#!/usr/bin/env python3
"""Restore persisted Binance session if missing after restart; confirm halt."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"

CMD = r"""
set -e
echo '=== env halt ==='
grep -E '^(SCANNER_EXEC|FORWARD_DRY_RUN)=' /etc/bilshenz.env || echo 'MISSING HALT FLAGS'
echo '=== journal restore ==='
journalctl -u bilshenz-binance-api --since '10 min ago' --no-pager | grep -iE 'session|restore|persisted|invalid|startup|STREAM|FORCE_MAINNET' | tail -60
echo '=== try load session in-process ==='
cd /opt/bilshenz/binance_trading_system/python
""" + PY + r""" - <<'PY'
import os, json, urllib.request
# ensure env
for line in open('/etc/bilshenz.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from session_store import load_binance_session
s=load_binance_session()
print('loaded', bool(s), 'testnet', (s or {}).get('testnet'), 'key_len', len((s or {}).get('api_key') or ''))
if not s:
    raise SystemExit(0)

# POST /api/login with restored keys to re-attach without phone
import urllib.request
body=json.dumps({
  'api_key': s['api_key'],
  'api_secret': s['api_secret'],
  'testnet': False,  # FORCE_MAINNET
}).encode()
tok=os.environ.get('BRIDGE_TOKEN','')
req=urllib.request.Request(
  'http://127.0.0.1:8766/api/login',
  data=body,
  headers={'Content-Type':'application/json','Authorization':f'Bearer {tok}'},
  method='POST',
)
try:
  with urllib.request.urlopen(req, timeout=30) as r:
    j=json.loads(r.read())
    print('login_ok', j.get('ok'), 'connected', j.get('connected'), 'error', j.get('error') or j.get('detail'))
except Exception as e:
  print('login_fail', e)
  try:
    print(e.read().decode()[:500])
  except Exception:
    pass

import time; time.sleep(2)
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
print('connected', h.get('connected'))
print('scanner_block', (h.get('scanner') or {}).get('exec_block'), 'can_execute', (h.get('scanner') or {}).get('can_execute'))
print('user_ws', (h.get('user_data_stream') or {}).get('ws_connected'))
print('tick', (h.get('tick_stream') or {}).get('ws_connected'), 'scanner_ws', (h.get('scanner_stream') or {}).get('ws_connected'))
PY
"""

pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
_, o, e = c.exec_command(CMD, timeout=60)
print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
err = e.read().decode("utf-8", "replace")
if err.strip():
    print(err.encode("ascii", "replace").decode("ascii")[-2000:])
c.close()
