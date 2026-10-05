#!/usr/bin/env python3
"""Upload hardened scanner/connector files and restart bridge."""
from __future__ import annotations

import os
import sys
from pathlib import Path

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
ROOT = Path(__file__).resolve().parents[2]
REMOTE_PY = "/opt/bilshenz/binance_trading_system/python"

FILES = [
    "momentum_scanner.py",
    "binance_connector.py",
    "test_adopt_exchange.py",
]


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for name in FILES:
        local = ROOT / "binance_trading_system" / "python" / name
        remote = f"{REMOTE_PY}/{name}"
        print(f"upload {local.name} -> {remote}")
        sftp.put(str(local), remote)
    sftp.close()
    cmd = r"""
set -e
cd /opt/bilshenz/binance_trading_system/python
python3 test_adopt_exchange.py
python3 test_frozen_strategy.py
systemctl restart bilshenz-binance-api
sleep 6
systemctl is-active bilshenz-binance-api
set -a; . /etc/bilshenz.env; set +a
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions > /tmp/pos.json
curl -sS -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/scanner/snapshot' > /tmp/snap.json
python3 <<'PY'
import json, time
h=json.load(open('/tmp/h.json'))
s=h.get('scanner') or {}
print('connected', h.get('connected'), 'active', s.get('active_symbol'), 'exec', s.get('can_execute'), 'block', s.get('exec_block'))
print('adopt_hint', 'wait ticks for Long1/Long2 re-arm on naked short past gates')
pos=json.load(open('/tmp/pos.json'))
for p in pos.get('positions') or []:
  if float(p.get('volume') or 0)>0:
    print('POS', p.get('symbol'), p.get('positionSide'), p.get('volume'), p.get('price_open'), 'lev', p.get('leverage'), 'xlev', p.get('exchange_leverage'))
snap=json.load(open('/tmp/snap.json'))
print('position_logic', snap.get('position_logic'))
for b in snap.get('blocks') or []:
  print('BLOCK', b)
# wait briefly for manage to re-arm
time.sleep(8)
import urllib.request
req=urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={'X-Bridge-Token': open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")})
# re-fetch via curl file after sleep done in shell
PY
sleep 12
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions > /tmp/pos2.json
curl -sS -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/scanner/snapshot' > /tmp/snap2.json
python3 <<'PY'
import json
pos=json.load(open('/tmp/pos2.json'))
snap=json.load(open('/tmp/snap2.json'))
print('=== AFTER SETTLE ===')
for p in pos.get('positions') or []:
  if float(p.get('volume') or 0)>0:
    print('POS', p.get('symbol'), p.get('positionSide') or p.get('type'), p.get('volume'), p.get('price_open'))
print('position_logic', snap.get('position_logic'))
for b in snap.get('blocks') or []:
  print('BLOCK', {k:b.get(k) for k in ('symbol','status','unrealizedPnl','legs','price')})
print('exec_events')
for e in (snap.get('execution_events') or [])[:6]:
  print(e.get('leg'), e.get('stage'), e.get('fill_price'), e.get('error'))
PY
grep -E 'AKEUSDT|adopt|LONG1|LONG2|repair|SIBLING|leverage .*stays|frozen' /var/log/bilshenz/app.log 2>/dev/null | tail -n 40
"""
    _, o, e = c.exec_command(cmd, timeout=120)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err[-3000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
