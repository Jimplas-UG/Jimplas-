#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

CMD = r"""
set -e
/opt/bilshenz/binance_trading_system/python/.venv/bin/python -m py_compile \
  /opt/bilshenz/binance_trading_system/python/main.py \
  /opt/bilshenz/binance_trading_system/python/binance_connector.py
echo COMPILE_OK
systemctl restart bilshenz-binance-api
sleep 7
python3 <<'PY'
import json, urllib.request
from pathlib import Path
d={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
  if '=' in l and not l.startswith('#'):
    k,v=l.split('=',1); d[k]=v.strip().strip('"').strip("'")
tok=d.get('BRIDGE_TOKEN','')
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read().decode())
s=h.get('scanner') or {}
print('connected', h.get('connected'), 'cool', h.get('rest_cool_s'), 'exec', s.get('can_execute'), 'active', s.get('active_symbol'))
body=json.dumps({
  'api_key': d.get('BINANCE_API_KEY',''),
  'api_secret': d.get('BINANCE_API_SECRET',''),
  'testnet': True,
  'auto_detect_env': True,
}).encode()
req=urllib.request.Request(
  'http://127.0.0.1:8766/api/login',
  data=body,
  method='POST',
  headers={'Content-Type':'application/json','X-Bridge-Token':tok},
)
try:
  with urllib.request.urlopen(req, timeout=25) as r:
    j=json.loads(r.read().decode())
    print('login', j.get('ok'), j.get('mode'), 'exec', j.get('can_execute'))
except Exception as ex:
  print('login_fail', type(ex).__name__, ex)
  if hasattr(ex, 'read'):
    try:
      print(ex.read().decode()[:400])
    except Exception:
      pass
PY
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    sftp.put(str(ROOT / "binance_trading_system/python/main.py"), "/opt/bilshenz/binance_trading_system/python/main.py")
    sftp.put(
        str(ROOT / "binance_trading_system/python/binance_connector.py"),
        "/opt/bilshenz/binance_trading_system/python/binance_connector.py",
    )
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-1500:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
