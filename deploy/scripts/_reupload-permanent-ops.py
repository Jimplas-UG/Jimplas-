#!/usr/bin/env python3
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

FILES = [
    "binance_trading_system/python/momentum_scanner.py",
    "binance_trading_system/python/binance_connector.py",
    "binance_trading_system/python/test_permanent_leak_locks.py",
]

CMD = r"""
set -e
cd /opt/bilshenz/binance_trading_system/python
# Bust stale bytecode that was shadowing the new source.
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
rm -f momentum_scanner.pyc binance_connector.pyc 2>/dev/null || true
.venv/bin/python -m py_compile momentum_scanner.py binance_connector.py
.venv/bin/python - <<'PY'
import importlib
import momentum_scanner as ms
import binance_connector as bc
importlib.reload(ms)
importlib.reload(bc)
import inspect
s = inspect.getsource(ms.MomentumScanner._execute_pending_short)
print('snapshot', '_snapshot_symbol_legs_to_sticky' in s)
print('prep5', 'leverage_5x_prepare_failed' in s)
print('naked', 'NAKED_LEVERAGE_LOCK' in inspect.getsource(ms.MomentumScanner._manage_positions))
print('force', '_force_confirm_short_open' in inspect.getsource(ms.MomentumScanner._ensure_pair_coherence))
print('retry_remote', 'remote end closed' in inspect.getsource(bc.BinanceConnector._parse_order_error).lower())
assert '_snapshot_symbol_legs_to_sticky' in s and 'leverage_5x_prepare_failed' in s
print('ALL_MARKERS_OK')
PY
.venv/bin/python test_permanent_leak_locks.py 2>&1 | tail -n 6
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 10
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
python3 - <<'PY'
import json, time, urllib.request
for i in range(15):
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
    sc=h.get('scanner') or {}
    print(i, 'can', sc.get('can_execute'), 'tracked', sc.get('symbols_tracked'), 'active', sc.get('active_symbol'))
    if h.get('connected') and sc.get('symbols_tracked', 0) > 50:
        break
    time.sleep(1)
tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
req=urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={'Authorization':'Bearer '+tok})
pos=json.loads(urllib.request.urlopen(req, timeout=15).read())
opens=[p for p in (pos.get('positions') or []) if abs(float(p.get('volume') or 0)) > 1e-12]
print('OPEN_N', len(opens))
for p in opens:
    print('OPEN', p.get('symbol'), p.get('positionSide'), 'ui', p.get('leverage'), 'ex', p.get('exchange_leverage'))
print('DEPLOY_LIVE_OK')
PY
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in FILES:
        sftp.put(str(ROOT / rel), f"/opt/bilshenz/{rel.replace(chr(92), '/')}")
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
