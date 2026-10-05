#!/usr/bin/env python3
"""Check auth block state and whether signed trading endpoints work."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"

CMD = r'''
cd /opt/bilshenz/binance_trading_system/python
''' + PY + r''' <<'PY'
import os, json, time, hmac, hashlib, urllib.request, urllib.parse
for line in open('/etc/bilshenz.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1); os.environ[k.strip()]=v.strip().strip('"').strip("'")
from session_store import load_binance_session
s=load_binance_session() or {}
key=(s.get('api_key') or os.environ.get('BINANCE_API_KEY','')).strip()
sec=(s.get('api_secret') or os.environ.get('BINANCE_API_SECRET','')).strip()
tok=os.environ.get('BRIDGE_TOKEN','').strip()

h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
sc=h.get('scanner') or {}
print('connected', h.get('connected'), 'can', sc.get('can_execute'), 'block', sc.get('exec_block'))
print('api_auth', sc.get('api_auth'))
print('last_exec_error', sc.get('last_exec_error'))

# signed leverage probe (same call that failed in prepare_symbol)
params={'symbol':'BTCUSDT','leverage':5,'timestamp':int(time.time()*1000)}
qs=urllib.parse.urlencode(params)
sig=hmac.new(sec.encode(), qs.encode(), hashlib.sha256).hexdigest()
url=f'https://fapi.binance.com/fapi/v1/leverage?{qs}&signature={sig}'
req=urllib.request.Request(url, method='POST', headers={'X-MBX-APIKEY':key})
try:
    with urllib.request.urlopen(req, timeout=10) as r:
        print('leverage_probe', r.status, r.read()[:120])
except Exception as e:
    body=''
    if hasattr(e,'read'):
        try: body=e.read().decode()[:200]
        except Exception: pass
    print('leverage_probe_FAIL', getattr(e,'code',None), e, body)

# recent after 09:14
import subprocess
print(subprocess.check_output(['bash','-lc',"awk '$0 >= \"2026-10-01T09:14:00\"' /var/log/bilshenz/binance-api.log | grep -iE '2015|API_AUTH|login ok|SHORT failed|EXEC_FAIL' | tail -30"], text=True, errors='replace'))
PY
'''

pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
_, o, e = c.exec_command(CMD, timeout=60)
print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
print(e.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii")[-1000:])
c.close()
