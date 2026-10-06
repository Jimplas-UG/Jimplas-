#!/usr/bin/env python3
"""Clear sticky exec_halt after Sep23 restore so open legs can be managed."""
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
PY=/opt/bilshenz/binance_trading_system/python/.venv/bin/python
$PY - <<'PY'
import json, urllib.request
from pathlib import Path
tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
H={'Authorization':'Bearer '+tok,'Content-Type':'application/json'}
risk=Path('/var/lib/bilshenz/scanner-risk.json')
if risk.exists():
    raw=json.loads(risk.read_text() or '{}')
    if isinstance(raw, dict):
        raw['exec_halted']=False
        raw['partition_usd']=100.0
        raw['partition_usd_locked']=True
        risk.write_text(json.dumps(raw, indent=2)+'\n')
        print('RISK', {k: raw.get(k) for k in ('partition_usd','exec_halted','locked')})
req=urllib.request.Request('http://127.0.0.1:8766/api/scanner/exec', data=b'{"enabled":true}', headers=H, method='POST')
print('EXEC', json.loads(urllib.request.urlopen(req, timeout=20).read()))
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {}
print('AFTER can', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'), 'part', sc.get('partition_usd'), 'err', sc.get('last_exec_error'))
pos=json.loads(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8766/api/positions', headers=H), timeout=20).read())
items=[p for p in (pos.get('positions') or []) if abs(float(p.get('volume') or 0))>1e-12]
print('OPEN', [(p.get('symbol'), p.get('positionSide'), p.get('volume'), p.get('leverage'), round(float(p.get('profit') or 0),2)) for p in items])
PY
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=45)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err.encode("ascii", "replace").decode("ascii")[-400:])
    c.close()


if __name__ == "__main__":
    main()
