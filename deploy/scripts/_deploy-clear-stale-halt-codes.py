#!/usr/bin/env python3
"""Deploy stale rule_halt clear on resume; keep trading armed (do not leave halt)."""
from __future__ import annotations

from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE = "/opt/bilshenz/binance_trading_system/python"
PY = f"{REMOTE}/.venv/bin/python"
FILES = [
    "binance_trading_system/python/momentum_scanner.py",
    "binance_trading_system/python/test_exec_session.py",
]

CMD = rf"""
set -e
cd {REMOTE}
{PY} -m py_compile momentum_scanner.py
{PY} test_exec_session.py
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 8
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
{PY} - <<'PY'
import json, urllib.request, time
tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
H={{'Authorization':'Bearer '+tok,'Content-Type':'application/json'}}

# Ensure risk file not leaving halt
from pathlib import Path
risk=Path('/var/lib/bilshenz/scanner-risk.json')
if risk.exists():
    raw=json.loads(risk.read_text() or '{{}}')
    if isinstance(raw, dict) and raw.get('exec_halted'):
        raw['exec_halted']=False
        raw['partition_usd']=100.0
        risk.write_text(json.dumps(raw, indent=2)+'\n')
        print('CLEARED_PERSISTED_HALT')

for i in range(25):
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
    sc=h.get('scanner') or {{}}
    if h.get('connected'):
        break
    time.sleep(0.5)

# Clear stale halt codes even if already armed
req=urllib.request.Request(
    'http://127.0.0.1:8766/api/scanner/exec',
    data=json.dumps({{'enabled': True}}).encode(),
    headers=H,
    method='POST',
)
print('EXEC', json.loads(urllib.request.urlopen(req, timeout=10).read()))

h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {{}}
print('LIVE can', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'), 'block', sc.get('exec_block'), 'active', sc.get('active_symbol'))
print('rule_kernel', sc.get('rule_kernel'))
reqp=urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={{'Authorization':'Bearer '+tok}})
pos=json.loads(urllib.request.urlopen(reqp, timeout=12).read())
items=[p for p in (pos.get('positions') or []) if float(p.get('volume') or 0)>1e-12]
print('POS', len(items))
for p in items:
    print(' ', p.get('symbol'), p.get('positionSide'), p.get('volume'), 'lev', p.get('leverage') or p.get('exchange_leverage'))
assert sc.get('can_execute') is True, sc
assert not sc.get('user_exec_halted'), sc
assert (sc.get('rule_kernel') or {{}}).get('halt_codes') in ([], None), sc.get('rule_kernel')
print('POST_MANUAL_CLOSE_HYGIENE_OK')
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
        print(err.encode("ascii", "replace").decode("ascii")[-2500:])
    c.close()


if __name__ == "__main__":
    main()
