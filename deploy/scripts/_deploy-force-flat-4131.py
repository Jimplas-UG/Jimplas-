#!/usr/bin/env python3
"""Deploy -4131 force-flat close harden; flatten stuck ORCA; keep halt until flat then re-arm only if book clean."""
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
    "binance_trading_system/python/momentum_scanner.py",
    "binance_trading_system/python/frozen_strategy.py",
    "binance_trading_system/python/test_violation_locks.py",
    "binance_trading_system/python/test_close_orders.py",
    "binance_trading_system/python/test_exec_session.py",
]

CMD = rf"""
set -e
cd {REMOTE}
{PY} -m py_compile binance_connector.py momentum_scanner.py frozen_strategy.py
{PY} test_close_orders.py
{PY} test_violation_locks.py
{PY} test_frozen_strategy.py
{PY} test_rule_kernel.py
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 8
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
{PY} - <<'PY'
import json, time, urllib.request
from pathlib import Path

tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
H={{'Authorization':'Bearer '+tok,'Content-Type':'application/json'}}

def get(url):
    req=urllib.request.Request(url, headers=H)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def post(url, body):
    req=urllib.request.Request(url, data=json.dumps(body).encode(), headers=H, method='POST')
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read().decode())

# Wait connected
for i in range(30):
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
    if h.get('connected'):
        break
    time.sleep(0.5)

pos=get('http://127.0.0.1:8766/api/positions')
items=[p for p in (pos.get('positions') or []) if float(p.get('volume') or 0)>1e-12]
print('BEFORE_POS', [(p.get('symbol'), p.get('positionSide'), p.get('volume'), p.get('leverage')) for p in items])

# Force-close every open symbol (stuck exits)
for p in items:
    sym=str(p.get('symbol') or '').upper()
    if not sym:
        continue
    print('FORCE_CLOSE', sym)
    try:
        r=post('http://127.0.0.1:8766/api/close', {{'symbol': sym, 'close_pair': True}})
        print('CLOSE', json.dumps(r, default=str)[:500])
    except Exception as e:
        body=getattr(e,'read',lambda:b'')()
        print('CLOSE_ERR', e, body[:400] if body else '')

# Poll flat up to 90s
flat=False
for i in range(45):
    time.sleep(2)
    pos=get('http://127.0.0.1:8766/api/positions')
    items=[p for p in (pos.get('positions') or []) if float(p.get('volume') or 0)>1e-12]
    print(i, 'left', [(p.get('symbol'), p.get('volume')) for p in items])
    if not items:
        flat=True
        break
    # keep hammering
    for p in items:
        sym=str(p.get('symbol') or '').upper()
        try:
            post('http://127.0.0.1:8766/api/close', {{'symbol': sym, 'close_pair': True}})
        except Exception as e:
            print('retry_err', sym, e)

if not flat:
    raise SystemExit('STILL_OPEN_AFTER_FORCE_FLAT')

# Clear halt and re-arm only when flat
risk=Path('/var/lib/bilshenz/scanner-risk.json')
if risk.exists():
    raw=json.loads(risk.read_text() or '{{}}')
    if isinstance(raw, dict):
        raw['exec_halted']=False
        raw['partition_usd']=100.0
        risk.write_text(json.dumps(raw, indent=2)+'\n')
        print('CLEARED_RISK_HALT')

r=post('http://127.0.0.1:8766/api/scanner/exec', {{'enabled': True}})
print('EXEC', r)
time.sleep(2)
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {{}}
print('AFTER can', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'), 'block', sc.get('exec_block'))
print('kernel', sc.get('rule_kernel'), 'stuck', sc.get('stuck_close_symbols'))
assert sc.get('can_execute') is True, sc
assert not sc.get('user_exec_halted'), sc
assert not (sc.get('stuck_close_symbols') or []), sc
print('FORCE_FLAT_4131_DEPLOY_OK')
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
    _, o, e = c.exec_command(CMD, timeout=300)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print(err.encode("ascii", "replace").decode("ascii")[-3000:])
    c.close()


if __name__ == "__main__":
    main()
