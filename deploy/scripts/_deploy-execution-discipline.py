#!/usr/bin/env python3
"""Deploy SAFE_MODE / oversize / close-verify / fill-resolve locks to FRA."""
from __future__ import annotations

from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE = "/opt/bilshenz/binance_trading_system/python"
PY = f"{REMOTE}/.venv/bin/python"

FILES = [
    "binance_trading_system/python/binance_connector.py",
    "binance_trading_system/python/frozen_strategy.py",
    "binance_trading_system/python/main.py",
    "binance_trading_system/python/momentum_scanner.py",
    "binance_trading_system/python/rule_kernel.py",
    "binance_trading_system/python/test_rule_kernel.py",
    "binance_trading_system/python/test_execution_discipline.py",
    "binance_trading_system/python/test_violation_locks.py",
    "binance_trading_system/python/test_close_orders.py",
]

CMD = rf"""
set -e
cd {REMOTE}
{PY} -m py_compile binance_connector.py frozen_strategy.py main.py momentum_scanner.py rule_kernel.py
{PY} test_violation_locks.py
{PY} test_rule_kernel.py
{PY} test_close_orders.py
{PY} test_execution_discipline.py
{PY} - <<'PY'
from frozen_strategy import assert_frozen_contract
import inspect
from binance_connector import BinanceConnector
from momentum_scanner import MomentumScanner
snap = assert_frozen_contract()
assert hasattr(BinanceConnector, '_resolve_executed_qty')
assert hasattr(BinanceConnector, 'query_order')
assert hasattr(BinanceConnector, 'reset_leverage_if_flat')
assert hasattr(BinanceConnector, '_limit_ioc_open_leg')
assert '_resolve_executed_qty' in inspect.getsource(BinanceConnector.close_position)
assert 'CLOSE_INCOMPLETE' in open('momentum_scanner.py', encoding='utf-8').read()
assert 'HEDGE_OPEN_FAIL' in open('momentum_scanner.py', encoding='utf-8').read()
assert 'reset_leverage_if_flat' in inspect.getsource(MomentumScanner._close_all)
assert 'Flat on exchange' in inspect.getsource(MomentumScanner._close_succeeded)
print('CONTRACT', snap['strategy_id'], 'part', snap['ops']['partition_usd'])
print('EXEC_DISCIPLINE_MARKERS_OK')
PY
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 8
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
{PY} - <<'PY'
import json, urllib.request
tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
H={{'Authorization':'Bearer '+tok}}
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {{}}
print('LIVE', h.get('mode'), 'conn', h.get('connected'), 'can', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'), 'part', sc.get('partition_usd'), 'safe', sc.get('safe_mode'), 'stuck', sc.get('stuck_close_symbols'), 'err', sc.get('last_exec_error'))
print('EXEC_DISCIPLINE_DEPLOY_OK')
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
    _, o, e = c.exec_command(CMD, timeout=240)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err.encode("ascii", "replace").decode("ascii")[-2500:])
    c.close()


if __name__ == "__main__":
    main()
