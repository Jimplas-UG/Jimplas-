#!/usr/bin/env python3
"""Deploy close-abort + side/leg chunk fixes; keep emergency halt."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE = "/opt/bilshenz/binance_trading_system/python"
PY = f"{REMOTE}/.venv/bin/python"
FILES = [
    "binance_trading_system/python/binance_connector.py",
    "binance_trading_system/python/momentum_scanner.py",
    "binance_trading_system/python/frozen_strategy.py",
    "binance_trading_system/python/test_violation_locks.py",
    "binance_trading_system/python/test_exec_session.py",
]
CMD = rf"""
set -e
cd {REMOTE}
{PY} -m py_compile binance_connector.py momentum_scanner.py frozen_strategy.py
{PY} test_violation_locks.py
{PY} test_frozen_strategy.py
{PY} test_exec_session.py
{PY} test_rule_kernel.py
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 8
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
{PY} - <<'PY'
import json, urllib.request
tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
req=urllib.request.Request(
    'http://127.0.0.1:8766/api/scanner/exec',
    data=json.dumps({{'enabled': False}}).encode(),
    headers={{'Authorization':'Bearer '+tok,'Content-Type':'application/json'}},
    method='POST',
)
print('HALT', json.loads(urllib.request.urlopen(req, timeout=10).read()))
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {{}}
print('LIVE can', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'), 'part', sc.get('partition_usd'))
reqp=urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={{'Authorization':'Bearer '+tok}})
pos=json.loads(urllib.request.urlopen(reqp, timeout=12).read())
print('POS', len(pos.get('positions') or []))
print('CLOSE_ABORT_DEPLOY_OK')
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in FILES:
        sftp.put(str(ROOT / rel), f"/opt/bilshenz/{rel}")
        print("uploaded", rel)
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=180)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err.encode("ascii", "replace").decode("ascii")[-1500:])
    c.close()

if __name__ == "__main__":
    main()
