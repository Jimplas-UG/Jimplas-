#!/usr/bin/env python3
"""How many scanner market rows the bridge is actually serving."""
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
python3 - <<'PY'
import json, urllib.request, os
tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
req=urllib.request.Request('http://127.0.0.1:8766/api/scanner/snapshot', headers={'X-Bridge-Token': tok})
try:
    d=json.loads(urllib.request.urlopen(req, timeout=12).read())
except Exception as e:
    print('SNAPSHOT_ERR', e)
    raise SystemExit(1)
rows=d.get('rows') or []
meta={k:d.get(k) for k in ('watchlist','tracked','universe','can_execute','exec_block','user_exec_halted','partition_usd','strategy_id','strategy_variant') if k in d or True}
sc=d.get('meta') or d
print('rows', len(rows))
print('keys', sorted(d.keys())[:40])
status={}
for r in rows:
    s=str(r.get('status') or '?')
    status[s]=status.get(s,0)+1
print('by_status', status)
print('top', [(r.get('symbol'), r.get('status'), r.get('pct15m'), r.get('pct24h'), r.get('retracePct') or r.get('retrace_pct')) for r in rows[:12]])
# health scanner bit
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
s=h.get('scanner') or {}
print('health_can', s.get('can_execute'), 'block', s.get('exec_block') or s.get('exec_block_reason'))
print('health_watch', s.get('watchlist'), 'tracked', s.get('tracked'), 'coins', s.get('coins'), 'universe', s.get('universe'))
print('cool', h.get('rest_cool_s'), 'conn', h.get('connected'))
PY
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err[-800:])
    c.close()


if __name__ == "__main__":
    main()
