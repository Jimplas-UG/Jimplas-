#!/usr/bin/env python3
"""Get PORTAL lifecycle + halt trading + attempt chunked orphan flatten."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=45, look_for_keys=False, allow_agent=False)

CMD = r'''
set -e
cd /opt/bilshenz/binance_trading_system/python

echo '=== PORTAL LIFECYCLE ==='
grep -E 'PORTALUSDT.*(SHORT|LONG1|LONG2|closed|INVALIDATION|RESCUE|SMART|PULLBACK|orphan|EXEC_|flatten|SIBLING|TP)' /var/log/bilshenz/binance-api.log /var/log/bilshenz/binance-api.log.1 2>/dev/null | grep -E '2026-10-04T21:5|2026-10-04T22:0|2026-10-04T22:1' | head -n 120

.venv/bin/python - <<'PY'
import json, urllib.request, time

tok = open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")

# 1) Emergency halt
req = urllib.request.Request(
    'http://127.0.0.1:8766/api/scanner/exec',
    data=json.dumps({'enabled': False}).encode(),
    headers={'Authorization': 'Bearer ' + tok, 'Content-Type': 'application/json'},
    method='POST',
)
try:
    r = json.loads(urllib.request.urlopen(req, timeout=10).read())
    print('HALT', r)
except Exception as e:
    print('HALT_ERR', e)
    # try alternate
    req = urllib.request.Request(
        'http://127.0.0.1:8766/api/scanner/exec?enabled=false',
        headers={'Authorization': 'Bearer ' + tok},
        method='POST',
    )
    try:
        print('HALT2', urllib.request.urlopen(req, timeout=10).read()[:300])
    except Exception as e2:
        print('HALT2_ERR', e2)

# 2) Live positions via connector with session keys from running process env
import os
# Load bilshenz env into process for connector
for line in open('/etc/bilshenz.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1)
    os.environ.setdefault(k, v.strip().strip('"').strip("'"))

# Prefer API status positions with force
req = urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={'Authorization':'Bearer '+tok})
try:
    pos = json.loads(urllib.request.urlopen(req, timeout=15).read())
    print('API_POS', json.dumps(pos)[:2000])
except Exception as e:
    print('API_POS_ERR', e)

# Health after halt
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {}
print('AFTER_HALT can', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'), 'block', sc.get('exec_block'), 'active', sc.get('active_symbol'))

# MARKET max for PORTAL
import urllib.request as u
data=json.loads(u.urlopen('https://testnet.binancefuture.com/fapi/v1/exchangeInfo', timeout=30).read())
for s in data['symbols']:
    if s['symbol']=='PORTALUSDT':
        f={x['filterType']:x for x in s['filters']}
        print('PORTAL LOT', f.get('LOT_SIZE'))
        print('PORTAL MARKET', f.get('MARKET_LOT_SIZE'))
        break
PY
'''

_, o, e = c.exec_command(CMD, timeout=120)
print(o.read().decode('utf-8','replace').encode('ascii','replace').decode('ascii'))
err=e.read().decode('utf-8','replace')
if err.strip():
    print('STDERR', err.encode('ascii','replace').decode('ascii')[-2500:])
c.close()
