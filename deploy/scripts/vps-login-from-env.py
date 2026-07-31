#!/usr/bin/env python3
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
python3 - <<'PY'
import os
# mimic service env load
vals={}
for line in open('/etc/bilshenz.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1)
    vals[k]=v.strip().strip('"').strip("'")
for k in ['BINANCE_API_KEY','BINANCE_API_SECRET','BINANCE_TESTNET','BINANCE_PAPER']:
    v=vals.get(k,'')
    print(k, 'len=', len(v), 'empty=', (not v), 'testnet_flag=', v if k=='BINANCE_TESTNET' else '')
PY
# Try login via API using env keys loaded in a one-shot python against running process is hard —
# Instead call /api/login with keys from env file (server-side script).
python3 - <<'PY'
import json, urllib.request
vals={}
for line in open('/etc/bilshenz.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1)
    vals[k]=v.strip().strip('"').strip("'")
token=vals.get('BRIDGE_TOKEN','')
key=vals.get('BINANCE_API_KEY','')
secret=vals.get('BINANCE_API_SECRET','')
print('ready_login', bool(key and secret and token), 'keylen', len(key), 'seclen', len(secret))
body=json.dumps({'api_key': key, 'api_secret': secret, 'testnet': True}).encode()
req=urllib.request.Request('http://127.0.0.1:8766/api/login', data=body, method='POST', headers={'Content-Type':'application/json','X-Bridge-Token':token})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        print('login_testnet', r.status, r.read()[:300])
except Exception as e:
    print('login_testnet_fail', e)
    body=json.dumps({'api_key': key, 'api_secret': secret, 'testnet': False}).encode()
    req=urllib.request.Request('http://127.0.0.1:8766/api/login', data=body, method='POST', headers={'Content-Type':'application/json','X-Bridge-Token':token})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            print('login_mainnet', r.status, r.read()[:300])
    except Exception as e2:
        print('login_mainnet_fail', e2)
PY
curl -sS http://127.0.0.1:8766/health | python3 -c 'import sys,json; h=json.load(sys.stdin); s=h.get("scanner") or {}; print({"mode":h.get("mode"),"connected":h.get("connected"),"can_execute":s.get("can_execute"),"exec_block":s.get("exec_block")})'
"""


def main() -> int:
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=25, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err)
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
