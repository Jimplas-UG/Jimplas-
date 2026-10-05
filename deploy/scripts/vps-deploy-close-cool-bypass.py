#!/usr/bin/env python3
"""Deploy emergency-close REST-cool bypass to FRA."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

FILES = (
    "binance_trading_system/python/binance_connector.py",
    "binance_trading_system/python/main.py",
    "frontend/broker/binanceFuturesApi.js",
)

CMD = r"""
set -e
VENV=/opt/bilshenz/binance_trading_system/python/.venv/bin/python
$VENV -m py_compile \
  /opt/bilshenz/binance_trading_system/python/binance_connector.py \
  /opt/bilshenz/binance_trading_system/python/main.py
echo COMPILE_OK
systemctl restart bilshenz-binance-api
sleep 6
python3 <<'PY'
import json, urllib.request
from pathlib import Path
d={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
  if '=' in l and not l.startswith('#'):
    k,v=l.split('=',1); d[k]=v.strip().strip('"').strip("'")
tok=d.get('BRIDGE_TOKEN','')
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read().decode())
print('cool', h.get('rest_cool_s'), 'connected', h.get('connected'))
req=urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={'X-Bridge-Token': tok})
with urllib.request.urlopen(req, timeout=15) as r:
  j=json.loads(r.read().decode())
print('positions', [(p.get('symbol'), p.get('positionSide'), p.get('volume')) for p in (j.get('positions') or [])])
src=open('/opt/bilshenz/binance_trading_system/python/binance_connector.py').read()
print('has_bypass', 'bypass_rest_cool' in src)
print('has_wait_close', '_wait_or_clear_cool_for_close' in src)
PY
systemctl is-active bilshenz-binance-api
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in FILES:
        data = (ROOT / rel).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        with sftp.file(f"/opt/bilshenz/{rel}", "wb") as f:
            f.write(data)
        print("uploaded", rel)
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
