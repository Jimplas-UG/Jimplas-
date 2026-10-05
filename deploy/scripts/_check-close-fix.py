#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
systemctl is-active bilshenz-binance-api || systemctl restart bilshenz-binance-api
sleep 3
python3 <<'PY'
import json, urllib.request
from pathlib import Path
d={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
  if '=' in l and not l.startswith('#'):
    k,v=l.split('=',1); d[k]=v.strip().strip('"').strip("'")
tok=d.get('BRIDGE_TOKEN','')
try:
  h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read().decode())
  print('health_ok', h.get('ok'), 'cool', h.get('rest_cool_s'), 'connected', h.get('connected'))
except Exception as e:
  print('health_err', e)
src=open('/opt/bilshenz/binance_trading_system/python/binance_connector.py').read()
print('has_bypass', 'bypass_rest_cool' in src and '_wait_or_clear_cool_for_close' in src)
req=urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={'X-Bridge-Token': tok})
try:
  with urllib.request.urlopen(req, timeout=20) as r:
    j=json.loads(r.read().decode())
  pos=j.get('positions') or []
  print('n_pos', len(pos), 'cool', j.get('rest_cool_s'), 'stale', j.get('stale'))
  for p in pos[:8]:
    print(' POS', p.get('symbol'), p.get('positionSide'), p.get('volume'), p.get('profit'))
except Exception as e:
  print('pos_err', e)
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-800:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
