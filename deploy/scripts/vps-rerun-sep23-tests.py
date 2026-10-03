#!/usr/bin/env python3
"""Deploy updated unit tests + re-run Sep23 quant battery on FRA."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE = "/opt/bilshenz/binance_trading_system/python"
PY = f"{REMOTE}/.venv/bin/python"

FILES = [
    "binance_trading_system/python/test_strategy_guards.py",
    "binance_trading_system/python/test_exec_session.py",
]

CMD = rf"""
set -e
cd {REMOTE}
{PY} test_frozen_strategy.py
{PY} test_strategy_guards.py
{PY} test_execution_engine.py
{PY} test_exec_session.py
echo LOCAL_UNITS_OK
# live confirm snippet
{PY} - <<'PY'
from frozen_strategy import assert_frozen_contract
import json, urllib.request
snap=assert_frozen_contract()
print('CONTRACT', snap['strategy_id'], snap['ops'])
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {{}}
assert sc.get('strategy_id')=='short_first_v1'
assert float(sc.get('partition_usd'))==100.0
assert sc.get('partition_usd_locked') is True
assert float(sc.get('short_partition_pct'))==50
assert float(sc.get('long1_partition_pct'))==40
assert float(sc.get('long2_partition_pct'))==40
assert sc.get('can_execute') is True
print('LIVE_OK mode', h.get('mode'), 'connected', h.get('connected'), 'part', sc.get('partition_usd'))
print('ALL_GREEN')
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
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
    print("EXIT", o.channel.recv_exit_status())
    c.close()

if __name__ == "__main__":
    main()
