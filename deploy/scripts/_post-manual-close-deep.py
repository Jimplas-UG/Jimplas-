#!/usr/bin/env python3
"""Deep post-manual-close check: NIL/BOB legs, kernel halt, recent app log."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
import json, urllib.request

tok = open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
H = {'Authorization': 'Bearer ' + tok}

def get(url):
    req = urllib.request.Request(url, headers=H)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

h = json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc = h.get('scanner') or {}
print('SCANNER_JSON')
print(json.dumps(sc, default=str, indent=2)[:5000])
print('---')
pos = get('http://127.0.0.1:8766/api/positions')
items = pos.get('positions') or []
print('ALL_POS_COUNT', len(items))
for p in items:
    print(json.dumps(p, default=str)[:600])
bob = [p for p in items if 'BOB' in str(p.get('symbol') or '').upper()]
nil = [p for p in items if 'NIL' in str(p.get('symbol') or '').upper()]
print('BOB_LEGS', bob)
print('NIL_LEGS', json.dumps(nil, default=str)[:2000])
print('rule_kernel', sc.get('rule_kernel'))
print('can_execute', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'), 'block', sc.get('exec_block'), 'active', sc.get('active_symbol'))
PY

echo '=== APP LOG NIL/BOB/KERNEL ==='
grep -E 'NILUSDT|1000000BOBUSDT|NAKED_SHORT|RULE_KERNEL|MANUAL_|CLOSE_OK|CLOSE_FAILED|adopt|independent|hedge_episode|long1_was|ORPHAN|PARTIAL_CLOSE' /var/log/bilshenz/app.log | tail -n 100
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, stdout, stderr = client.exec_command(CMD, timeout=120)
    sys.stdout.write(stdout.read().decode("utf-8", "replace"))
    err = stderr.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
