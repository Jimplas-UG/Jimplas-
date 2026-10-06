#!/usr/bin/env python3
"""Close any open FRA legs once, clear halt if flat, re-arm. Short timeout."""
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set -e
TOK=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
AUTH="Authorization: Bearer $TOK"
PY=/opt/bilshenz/binance_trading_system/python/.venv/bin/python
curl -sS -H "$AUTH" http://127.0.0.1:8766/api/positions > /tmp/pos.json
$PY - <<'PY'
import json, urllib.request
tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
H={'Authorization':'Bearer '+tok,'Content-Type':'application/json'}
pos=json.load(open('/tmp/pos.json'))
items=[p for p in (pos.get('positions') or []) if abs(float(p.get('volume') or p.get('positionAmt') or 0))>1e-12]
print('OPEN', [(p.get('symbol'), p.get('positionSide') or p.get('type'), p.get('volume'), p.get('leverage')) for p in items])
for p in items:
    sym=str(p.get('symbol') or '').upper()
    body=json.dumps({'symbol':sym,'close_pair':True}).encode()
    req=urllib.request.Request('http://127.0.0.1:8766/api/close', data=body, headers=H, method='POST')
    try:
        r=json.loads(urllib.request.urlopen(req, timeout=90).read())
        print('CLOSE', sym, 'ok', r.get('ok'), 'status', r.get('status'), 'err', r.get('error'))
    except Exception as e:
        print('CLOSE_ERR', sym, e)
pos2=json.loads(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8766/api/positions', headers=H), timeout=20).read())
left=[p for p in (pos2.get('positions') or []) if abs(float(p.get('volume') or p.get('positionAmt') or 0))>1e-12]
print('LEFT', len(left), [(p.get('symbol'), p.get('volume')) for p in left])
if left:
    raise SystemExit('NOT_FLAT')
# clear halt file
from pathlib import Path
risk=Path('/var/lib/bilshenz/scanner-risk.json')
if risk.exists():
    raw=json.loads(risk.read_text() or '{}')
    if isinstance(raw, dict):
        raw['exec_halted']=False
        raw['partition_usd']=100.0
        risk.write_text(json.dumps(raw, indent=2)+'\n')
        print('CLEARED_HALT_FILE')
req=urllib.request.Request('http://127.0.0.1:8766/api/scanner/exec', data=b'{"enabled":true}', headers=H, method='POST')
print('EXEC', json.loads(urllib.request.urlopen(req, timeout=20).read()))
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {}
print('AFTER can', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'), 'part', sc.get('partition_usd'))
PY
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=150)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err.encode("ascii", "replace").decode("ascii")[-800:])
    c.close()


if __name__ == "__main__":
    main()
