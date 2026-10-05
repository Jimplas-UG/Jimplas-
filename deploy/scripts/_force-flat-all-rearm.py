#!/usr/bin/env python3
"""Force-close all open FRA positions (ORCA -4131 stuck), clear halt, re-arm."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
import json, time, urllib.request
from pathlib import Path

tok = open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
H = {'Authorization': 'Bearer ' + tok, 'Content-Type': 'application/json'}

def get(url):
    req = urllib.request.Request(url, headers=H)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=H, method='POST')
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())

pos = get('http://127.0.0.1:8766/api/positions')
items = [p for p in (pos.get('positions') or []) if float(p.get('volume') or 0) > 1e-12]
print('BEFORE', [(p.get('symbol'), p.get('volume'), p.get('leverage'), p.get('profit')) for p in items])

for p in items:
    sym = str(p.get('symbol') or '').upper()
    print('CLOSE', sym)
    try:
        r = post('http://127.0.0.1:8766/api/close', {'symbol': sym, 'close_pair': True})
        print('CLOSE_R ok', r.get('ok'), 'flat', r.get('verified_flat'), 'cleared', r.get('positions_cleared'), 'status', r.get('status'), 'err', r.get('error'))
    except Exception as e:
        body = getattr(e, 'read', lambda: b'')()
        print('CLOSE_ERR', e, body[:400] if body else '')

flat = False
for i in range(45):
    time.sleep(2)
    pos = get('http://127.0.0.1:8766/api/positions')
    items = [p for p in (pos.get('positions') or []) if float(p.get('volume') or 0) > 1e-12]
    print(i, 'left', [(p.get('symbol'), p.get('volume')) for p in items])
    if not items:
        flat = True
        break
    for p in items:
        sym = str(p.get('symbol') or '').upper()
        try:
            post('http://127.0.0.1:8766/api/close', {'symbol': sym, 'close_pair': True})
        except Exception as e:
            print('retry_err', sym, e)

if not flat:
    raise SystemExit('STILL_OPEN')

risk = Path('/var/lib/bilshenz/scanner-risk.json')
if risk.exists():
    raw = json.loads(risk.read_text() or '{}')
    if isinstance(raw, dict):
        raw['exec_halted'] = False
        raw['partition_usd'] = 100.0
        risk.write_text(json.dumps(raw, indent=2) + '\n')
        print('CLEARED_RISK_HALT')

r = post('http://127.0.0.1:8766/api/scanner/exec', {'enabled': True})
print('EXEC', r)
time.sleep(2)
h = json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc = h.get('scanner') or {}
st = get('http://127.0.0.1:8766/api/status')
pos = get('http://127.0.0.1:8766/api/positions')
items = [p for p in (pos.get('positions') or []) if float(p.get('volume') or 0) > 1e-12]
print('AFTER can', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'), 'pos', len(items), 'acct_profit', (st.get('account') or {}).get('profit'))
assert not items
assert sc.get('can_execute') is True
print('FLAT_REARMED_OK')
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, stdout, stderr = client.exec_command(CMD, timeout=240)
    sys.stdout.write(stdout.read().decode("utf-8", "replace"))
    err = stderr.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-2500:])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
