#!/usr/bin/env python3
"""Deploy Sep 23–25 baseline (f194e4e trading core) to FRA — no Oct cascade modules."""
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
    "binance_trading_system/python/execution_engine.py",
    "binance_trading_system/python/frozen_strategy.py",
    "binance_trading_system/python/main.py",
    "binance_trading_system/python/momentum_scanner.py",
    "binance_trading_system/python/scanner_stream.py",
    "binance_trading_system/python/tick_stream.py",
    "binance_trading_system/python/user_data_stream.py",
    "binance_trading_system/python/leverage_policy.py",
    "binance_trading_system/python/strategy_guards.py",
    "binance_trading_system/python/test_close_orders.py",
    "binance_trading_system/python/test_exec_session.py",
    "binance_trading_system/python/test_execution_engine.py",
    "binance_trading_system/python/test_strategy_guards.py",
    "binance_trading_system/python/test_frozen_strategy.py",
    "binance_trading_system/python/test_leverage_policy.py",
    "binance_trading_system/python/test_sep23_capital_locks.py",
    "binance_trading_system/python/test_desk_quality.py",
]

REMOVE = [
    f"{REMOTE}/rule_kernel.py",
    f"{REMOTE}/test_rule_kernel.py",
    f"{REMOTE}/test_violation_locks.py",
    f"{REMOTE}/test_execution_discipline.py",
]

CMD = rf"""
set -e
cd {REMOTE}
rm -f {' '.join(REMOVE)}
{PY} -m py_compile binance_connector.py frozen_strategy.py main.py momentum_scanner.py execution_engine.py leverage_policy.py strategy_guards.py
test ! -f rule_kernel.py
{PY} test_frozen_strategy.py
{PY} test_leverage_policy.py
{PY} test_strategy_guards.py
{PY} test_close_orders.py
{PY} test_execution_engine.py
{PY} test_sep23_capital_locks.py
{PY} test_desk_quality.py
{PY} - <<'PY'
from frozen_strategy import assert_frozen_contract
import inspect
from momentum_scanner import MomentumScanner
from binance_connector import BinanceConnector
snap = assert_frozen_contract()
assert snap['strategy_id'] == 'short_first_v1'
assert abs(float(snap['ops']['partition_usd']) - 100.0) < 1e-9
assert 'target = LONG1_LEVERAGE' not in inspect.getsource(MomentumScanner._manage_positions)
assert 'long_residual_abort_short' in inspect.getsource(BinanceConnector.close_position)
assert hasattr(MomentumScanner, '_solo_hedge_exit_allowed')
from binance_connector import PositionsUnavailable
pos_src = inspect.getsource(BinanceConnector.positions)
assert 'unavailable — not empty' in pos_src
assert 'raise PositionsUnavailable' in pos_src
assert 'coherence deferred' in inspect.getsource(MomentumScanner._ensure_pair_coherence)
assert 'positions_unavailable' in inspect.getsource(MomentumScanner._reconcile_from_exchange_locked)
print('CONTRACT', snap['strategy_id'], 'part', snap['ops']['partition_usd'])
assert hasattr(MomentumScanner, '_liquidity_ok')
assert 'confirmed_positions' in inspect.getsource(BinanceConnector)
print('SEP23_CAPITAL_LOCKS_OK')
print('POSITIONS_TRUTH_OK')
print('DESK_QUALITY_OK')
print('SEP23_BASELINE_MARKERS_OK')
PY
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 8
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
{PY} - <<'PY'
import json, urllib.request
tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {{}}
print('LIVE', h.get('mode'), 'conn', h.get('connected'), 'can', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'), 'part', sc.get('partition_usd'))
print('SEP23_DEPLOY_OK')
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
        print("STDERR", err.encode("ascii", "replace").decode("ascii")[-1200:])
    c.close()


if __name__ == "__main__":
    main()
