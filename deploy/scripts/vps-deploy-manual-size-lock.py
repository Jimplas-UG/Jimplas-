#!/usr/bin/env python3
"""Deploy manual partition cap + invalidation gate locks to FRA."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE = "/opt/bilshenz/binance_trading_system/python"
PY = f"{REMOTE}/.venv/bin/python"
FILES = [
    "binance_trading_system/python/momentum_scanner.py",
    "binance_trading_system/python/frozen_strategy.py",
    "binance_trading_system/python/main.py",
    "binance_trading_system/python/test_violation_locks.py",
]

CMD = rf"""
set -e
cd {REMOTE}
{PY} -m py_compile momentum_scanner.py frozen_strategy.py main.py test_violation_locks.py
{PY} test_violation_locks.py
{PY} test_frozen_strategy.py
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 7
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
{PY} - <<'PY'
import json, urllib.request
from frozen_strategy import assert_frozen_contract
snap=assert_frozen_contract()
print('CONTRACT_OK')
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {{}}
print('LIVE', h.get('mode'), 'can', sc.get('can_execute'), 'part', sc.get('partition_usd'))
# prove main has reject marker
assert 'manual_qty_exceeds_locked_partition' in open('main.py',encoding='utf-8').read()
print('MANUAL_SIZE_LOCK_LIVE')
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
    _, o, e = c.exec_command(CMD, timeout=120)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err.encode("ascii", "replace").decode("ascii")[-1500:])
    c.close()

if __name__ == "__main__":
    main()
