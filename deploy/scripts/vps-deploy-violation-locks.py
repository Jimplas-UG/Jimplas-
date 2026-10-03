#!/usr/bin/env python3
"""Deploy violation locks (naked 5x, paired hedge episode, no overlap) to FRA."""
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
    "binance_trading_system/python/test_violation_locks.py",
]

CMD = rf"""
set -e
cd {REMOTE}
{PY} -m py_compile momentum_scanner.py frozen_strategy.py test_violation_locks.py
{PY} test_violation_locks.py
{PY} test_frozen_strategy.py
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 7
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
{PY} - <<'PY'
import json, urllib.request, time, inspect
import momentum_scanner as ms
from frozen_strategy import assert_frozen_contract
from leverage_policy import symbol_exchange_leverage
assert symbol_exchange_leverage(False)==5
assert 'target = LONG1_LEVERAGE' not in inspect.getsource(ms.MomentumScanner._manage_positions)
assert hasattr(ms.MomentumScanner, '_solo_hedge_exit_allowed')
snap=assert_frozen_contract()
print('CONTRACT', snap['strategy_id'], 'paired_hold_after_hedge', snap['recovery'].get('paired_hold_after_hedge_episode'))
for i in range(12):
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
    sc=h.get('scanner') or {{}}
    if h.get('connected') and sc.get('can_execute'):
        print('LIVE', h.get('mode'), 'can', True, 'part', sc.get('partition_usd'), 'active', sc.get('active_symbol'))
        break
    time.sleep(1)
print('VIOLATION_LOCKS_DEPLOYED')
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
