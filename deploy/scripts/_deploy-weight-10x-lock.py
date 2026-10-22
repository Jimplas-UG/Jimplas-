#!/usr/bin/env python3
"""Deploy permanent weight-budget + naked-10x fail-closed locks."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
UPLOAD = [
    "binance_trading_system/python/binance_connector.py",
    "binance_trading_system/python/momentum_scanner.py",
    "binance_trading_system/python/main.py",
    "binance_trading_system/python/position_manager.py",
    "binance_trading_system/python/frozen_strategy.py",
    "binance_trading_system/python/leverage_policy.py",
    "binance_trading_system/python/test_permanent_leak_locks.py",
    "binance_trading_system/python/test_sep23_capital_locks.py",
]
CMD = r"""
set -e
echo '=== FORWARD BOT ==='
systemctl cat bilshenz-forward-bot 2>/dev/null | sed -n '1,25p' || true
ps -o args= -C python | head -n 8 || true
cd /opt/bilshenz/binance_trading_system/python
rm -rf __pycache__
.venv/bin/python test_permanent_leak_locks.py 2>&1 | tail -n 8
.venv/bin/python test_sep23_capital_locks.py 2>&1 | tail -n 4
systemctl restart bilshenz-binance-api
sleep 12
systemctl is-active bilshenz-binance-api
python3 - <<'PY'
import json, urllib.request
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {}
print('can', sc.get('can_execute'), 'cool', h.get('rest_cool_s'), 'tracked', sc.get('symbols_tracked'), 'part', sc.get('partition_usd'), 'active', sc.get('active_symbol'))
tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
req=urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={'Authorization':'Bearer '+tok})
pos=json.loads(urllib.request.urlopen(req, timeout=20).read())
opens=[p for p in (pos.get('positions') or []) if abs(float(p.get('volume') or 0))>1e-12]
print('OPEN_N', len(opens))
for p in opens:
    print('OPEN', p.get('symbol'), p.get('positionSide'), 'ui', p.get('leverage'), 'ex', p.get('exchange_leverage'))
src=open('binance_connector.py', encoding='utf-8').read()
print('MARK budget', '_reserve_local_weight' in src)
print('MARK fail_closed_10x', 'not treating as' in src or 'fail closed' in src)
print('MARK no_false_true', 'return True' in src.split('def ensure_exchange_leverage')[1].split('def invalidate_positions_cache')[0])
print('DEPLOY_OK')
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in UPLOAD:
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
