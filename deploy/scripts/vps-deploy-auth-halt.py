#!/usr/bin/env python3
"""Deploy API-auth halt (stop -2015 spam) + re-login working mainnet keys."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE_PY = "/opt/bilshenz/binance_trading_system/python"
PY = f"{REMOTE_PY}/.venv/bin/python"

FILES = [
    "binance_connector.py",
    "execution_engine.py",
    "momentum_scanner.py",
]

CMD = rf"""
set -euo pipefail
{PY} -m py_compile {REMOTE_PY}/binance_connector.py {REMOTE_PY}/execution_engine.py {REMOTE_PY}/momentum_scanner.py
systemctl restart bilshenz-binance-api
sleep 6
systemctl is-active bilshenz-binance-api
cd {REMOTE_PY}
{PY} <<'PY'
import os, json, time, urllib.request
for line in open('/etc/bilshenz.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1); os.environ[k.strip()]=v.strip().strip('"').strip("'")
from session_store import load_binance_session, save_binance_session
s=load_binance_session() or {{}}
key=(s.get('api_key') or os.environ.get('BINANCE_API_KEY','')).strip()
sec=(s.get('api_secret') or os.environ.get('BINANCE_API_SECRET','')).strip()
# Prefer session; also write env to match so restarts stay consistent
if key and sec:
    save_binance_session(key, sec, False)
tok=os.environ.get('BRIDGE_TOKEN','').strip()
body=json.dumps({{'api_key':key,'api_secret':sec,'testnet':False}}).encode()
req=urllib.request.Request('http://127.0.0.1:8766/api/login', data=body, method='POST',
    headers={{'Content-Type':'application/json','Authorization':f'Bearer {{tok}}'}})
with urllib.request.urlopen(req, timeout=45) as r:
    j=json.loads(r.read())
print('login_ok', j.get('ok'), 'server', (j.get('account') or {{}}).get('server'), 'bal', (j.get('account') or {{}}).get('balance'))
time.sleep(2)
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
sc=h.get('scanner') or {{}}
print('connected', h.get('connected'), 'can', sc.get('can_execute'), 'block', sc.get('exec_block'))
print('api_auth', sc.get('api_auth'))
print('user_ws', (h.get('user_data_stream') or {{}}).get('ws_connected'))
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for name in FILES:
        print("upload", name)
        sftp.put(str(ROOT / "binance_trading_system/python" / name), f"{REMOTE_PY}/{name}")
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=120)
    sys.stdout.write(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err.encode("ascii", "replace").decode("ascii")[-2000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
