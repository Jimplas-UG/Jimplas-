#!/usr/bin/env python3
"""Deploy naked-short 5x leak fix + verify frozen contract on FRA."""
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
]

CMD = rf"""
set -e
cd {REMOTE}
{PY} -m py_compile momentum_scanner.py frozen_strategy.py
{PY} test_frozen_strategy.py
{PY} - <<'PY'
from frozen_strategy import assert_frozen_contract
from leverage_policy import symbol_exchange_leverage
assert symbol_exchange_leverage(has_recovery_long=False)==5
assert symbol_exchange_leverage(has_recovery_long=True)==10
print('LEVERAGE_POLICY_OK')
snap=assert_frozen_contract()
print('CONTRACT_OK', snap['strategy_id'])
PY
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 7
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
{PY} - <<'PY'
import json, urllib.request, time
for i in range(15):
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
    sc=h.get('scanner') or {{}}
    print(i, 'mode', h.get('mode'), 'can', sc.get('can_execute'), 'active', sc.get('active_symbol'), 'part', sc.get('partition_usd'))
    if h.get('connected') and sc.get('can_execute'):
        break
    time.sleep(1)
# show open pos leverage
tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
req=urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={{'Authorization':'Bearer '+tok}})
pos=json.loads(urllib.request.urlopen(req, timeout=10).read()).get('positions') or []
for p in pos:
    print('POS', p.get('symbol'), p.get('positionSide'), 'lev', p.get('leverage'), 'policy', p.get('policy_leverage'), 'qty', p.get('volume'))
print('DEPLOY_OK')
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
