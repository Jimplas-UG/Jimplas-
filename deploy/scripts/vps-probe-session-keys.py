#!/usr/bin/env python3
"""Probe session vs env keys on FRA — no secrets printed."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
python3 <<'PY'
from pathlib import Path
import json, subprocess
paths=[
 '/var/lib/bilshenz/binance-session.json',
 '/opt/bilshenz/binance_trading_system/python/.binance_session.json',
]
for p in paths:
  fp=Path(p)
  if not fp.exists():
    print('session_missing', p); continue
  try:
    j=json.loads(fp.read_text() or '{}')
  except Exception as e:
    print('session_bad', p, e); continue
  print('session', p, 'testnet', j.get('testnet'), 'key_len', len(str(j.get('api_key') or '')), 'secret_len', len(str(j.get('api_secret') or '')), 'keys', list(j.keys())[:12])
# env lengths
d={}
for line in Path('/etc/bilshenz.env').read_text().splitlines():
  if '=' in line and not line.startswith('#'):
    k,v=line.split('=',1); d[k]=v.strip().strip('"').strip("'")
print('env_testnet', d.get('BINANCE_TESTNET'), 'force_main', d.get('BINANCE_FORCE_MAINNET'), 'env_key_len', len(d.get('BINANCE_API_KEY','')), 'env_sec_len', len(d.get('BINANCE_API_SECRET','')))
print('--- log ---')
print(subprocess.check_output(['bash','-lc',"grep -Ei 'login|Invalid API|FORCE_MAIN|mainnet keys|configure|session' /var/log/bilshenz/binance-api.log | tail -n 30"], text=True, errors='replace'))
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    sys.stdout.buffer.write(o.read())
    err = e.read()
    if err.strip():
        sys.stderr.buffer.write(err[-1000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
