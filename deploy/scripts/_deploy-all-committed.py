#!/usr/bin/env python3
"""One-shot deploy of all committed lock/reliability modules to FRA."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE = "/opt/bilshenz/binance_trading_system/python"
PY = f"{REMOTE}/.venv/bin/python"

FILES = [
    "binance_trading_system/python/binance_connector.py",
    "binance_trading_system/python/execution_engine.py",
    "binance_trading_system/python/frozen_strategy.py",
    "binance_trading_system/python/main.py",
    "binance_trading_system/python/momentum_scanner.py",
    "binance_trading_system/python/rule_kernel.py",
    "binance_trading_system/python/test_exec_session.py",
    "binance_trading_system/python/test_rule_kernel.py",
    "binance_trading_system/python/test_strategy_guards.py",
    "binance_trading_system/python/test_violation_locks.py",
]

CMD = rf"""
set -e
cd {REMOTE}
{PY} -m py_compile binance_connector.py execution_engine.py frozen_strategy.py main.py momentum_scanner.py rule_kernel.py
{PY} test_rule_kernel.py
{PY} test_violation_locks.py
{PY} test_frozen_strategy.py
{PY} test_strategy_guards.py
{PY} test_exec_session.py
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 8
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
{PY} - <<'PY'
import json, urllib.request, inspect
import momentum_scanner as ms
from frozen_strategy import assert_frozen_contract
from leverage_policy import symbol_exchange_leverage
assert symbol_exchange_leverage(has_recovery_long=False)==5
assert 'target = LONG1_LEVERAGE' not in inspect.getsource(ms.MomentumScanner._manage_positions)
assert hasattr(ms.MomentumScanner, '_solo_hedge_exit_allowed')
assert 'manual_qty_exceeds_locked_partition' in open('main.py',encoding='utf-8').read()
snap=assert_frozen_contract()
print('CONTRACT', snap['strategy_id'], 'part', snap['ops']['partition_usd'])
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {{}}
print('LIVE', h.get('mode'), 'conn', h.get('connected'), 'can', sc.get('can_execute'), 'part', sc.get('partition_usd'))
print('FULL_DEPLOY_OK')
PY
"""


def main() -> None:
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
        print("STDERR", err.encode("ascii", "replace").decode("ascii")[-2000:])
    c.close()


if __name__ == "__main__":
    main()
