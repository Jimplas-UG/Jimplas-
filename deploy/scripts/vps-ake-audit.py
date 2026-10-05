#!/usr/bin/env python3
"""Deep AKEUSDT / open-pair logic check."""
from __future__ import annotations

import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
set -a; . /etc/bilshenz.env; set +a
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions > /tmp/pos.json
curl -sS -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/scanner/snapshot' > /tmp/snap.json
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json
python3 <<'PY'
import json
pos=json.load(open('/tmp/pos.json'))
snap=json.load(open('/tmp/snap.json'))
h=json.load(open('/tmp/h.json'))
print('ALL POSITIONS:')
for p in pos.get('positions') or []:
  print(p)
print('BLOCKS:')
for b in snap.get('blocks') or []:
  print(b)
print('AKE row:')
for r in snap.get('rows') or []:
  if r.get('symbol')=='AKEUSDT':
    print(r)
print('scanner', snap.get('scanner') or h.get('scanner'))
# adverse math
entry=0.0044518
price=None
for r in snap.get('rows') or []:
  if r.get('symbol')=='AKEUSDT':
    price=float(r.get('price') or 0)
if price:
  adv=(price-entry)/entry*100
  print('adverse_pct', round(adv,4), 'price', price, 'entry', entry)
  print('long1_threshold', 2.0, 'met', adv>=2)
  print('long2_threshold', 4.0, 'met', adv>=4)
  print('short_tp', entry*(1-0.025), 'hit', price<=entry*(1-0.025))
PY
echo === AKE LOG ===
grep -E 'AKEUSDT|LONG1|LONG2|SHORT|orphan|flatten|sibling|adopt|PULLBACK|TP' /var/log/bilshenz/app.log 2>/dev/null | grep -i AKE | tail -n 80
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
