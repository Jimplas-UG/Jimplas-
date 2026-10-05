#!/usr/bin/env python3
"""Pull scanner snapshot + clear stale rule halt codes if trading is armed and book is healthy."""
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
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

snap = get('http://127.0.0.1:8766/api/scanner/snapshot')
print('SNAP_KEYS', list(snap.keys())[:40])
# print active-ish coins
coins = snap.get('coins') or snap.get('strategies') or snap.get('items') or []
if isinstance(coins, dict):
    items = list(coins.values())
elif isinstance(coins, list):
    items = coins
else:
    items = []
    print('snap_preview', json.dumps(snap, default=str)[:2500])

def interesting(c):
    if not isinstance(c, dict):
        return False
    st = str(c.get('status') or '')
    return bool(c.get('short') or c.get('long1') or c.get('long2') or st not in ('', 'WATCHING', 'watching', 'IDLE', 'idle')) or c.get('symbol') in ('NILUSDT','1000000BOBUSDT')

for c in items:
    if interesting(c):
        print('COIN', json.dumps(c, default=str)[:900])

# also search nested
raw = json.dumps(snap, default=str)
for needle in ('NILUSDT', '1000000BOBUSDT', 'SHORT', 'LONG1'):
    print(needle, 'count', raw.count(needle))
print('ACTIVE_SNIPPET')
# find NIL block
idx = raw.find('NILUSDT')
print(raw[max(0,idx-200):idx+800] if idx>=0 else 'no NIL')
idx2 = raw.find('1000000BOBUSDT')
print('BOB_SNIP', raw[max(0,idx2-200):idx2+800] if idx2>=0 else 'no BOB')
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, stdout, stderr = client.exec_command(CMD, timeout=60)
    sys.stdout.write(stdout.read().decode("utf-8", "replace"))
    err = stderr.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
