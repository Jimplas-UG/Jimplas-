#!/usr/bin/env python3
"""Diagnose Binance -2015 / HTTP 401 without printing secrets."""
from __future__ import annotations

from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"

CMD = r'''
set +e
echo '=== mode / exec ==='
grep -E '^(BINANCE_TESTNET|BINANCE_FORCE_|BINANCE_PAPER|SCANNER_EXEC|FORWARD_DRY_RUN)=' /etc/bilshenz.env
python3 <<'PY'
from pathlib import Path
raw=Path('/etc/bilshenz.env').read_text()
for ln in raw.splitlines():
    if not ln or ln.startswith('#') or '=' not in ln: continue
    k,v=ln.split('=',1)
    k=k.strip(); v=v.strip().strip('"').strip("'")
    if k in ('BINANCE_API_KEY','BINANCE_API_SECRET','BRIDGE_TOKEN','SESSION_ENC_KEY','DESK_API_KEY'):
        print(f'{k} len={len(v)} empty={not bool(v)}')
PY
echo '=== health ==='
curl -sS -m 5 http://127.0.0.1:8766/health | ''' + PY + r''' -c "
import sys,json
h=json.load(sys.stdin)
sc=h.get('scanner') or {}
print('connected', h.get('connected'), 'testnet', h.get('testnet'))
print('can', sc.get('can_execute'), 'block', sc.get('exec_block'), 'exec', sc.get('exec_enabled'))
print('user', h.get('user_data_stream'))
print('tick', (h.get('tick_stream') or {}).get('ws_connected'), 'scanner_ws', (h.get('scanner_stream') or {}).get('ws_connected'))
"
echo '=== recent -2015 / 401 / Invalid ==='
grep -iE '2015|Invalid API-key|HTTP.?401|permissions for action|EXEC_FAIL|listenKey' /var/log/bilshenz/binance-api.log | tail -40
echo '=== live signed ping (mainnet + testnet) via session/env ==='
cd /opt/bilshenz/binance_trading_system/python
''' + PY + r''' <<'PY'
import os, time, hmac, hashlib, urllib.request, urllib.parse, json
for line in open('/etc/bilshenz.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1)
    os.environ[k.strip()] = v.strip().strip('"').strip("'")

from session_store import load_binance_session
s = load_binance_session()
env_key = os.environ.get('BINANCE_API_KEY','').strip()
env_sec = os.environ.get('BINANCE_API_SECRET','').strip()
print('session_ok', bool(s), 'session_testnet', (s or {}).get('testnet'),
      'session_key_len', len((s or {}).get('api_key') or ''),
      'env_key_len', len(env_key),
      'keys_equal', bool(s) and (s.get('api_key')==env_key))

def probe(base, key, secret, label):
    if not key or not secret:
        print(label, 'skip_empty')
        return
    ts=int(time.time()*1000)
    qs=f'timestamp={ts}'
    sig=hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    url=f'{base}/fapi/v2/account?{qs}&signature={sig}'
    req=urllib.request.Request(url, headers={'X-MBX-APIKEY': key})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            j=json.loads(r.read())
            bal=None
            for a in j.get('assets') or []:
                if a.get('asset')=='USDT':
                    bal=a.get('availableBalance') or a.get('walletBalance')
            print(label, 'OK http', r.status, 'usdt_avail', bal, 'canTrade', j.get('canTrade'))
    except Exception as e:
        body=''
        code=None
        if hasattr(e, 'read'):
            try:
                body=e.read().decode('utf-8','replace')[:300]
            except Exception:
                pass
        if hasattr(e, 'code'):
            code=e.code
        print(label, 'FAIL http', code, str(e)[:120], 'body', body[:200])

# Prefer session keys if present
key = (s or {}).get('api_key') or env_key
sec = (s or {}).get('api_secret') or env_sec
probe('https://fapi.binance.com', key, sec, 'mainnet_session_or_env')
probe('https://testnet.binancefuture.com', key, sec, 'testnet_session_or_env')
if s and env_key and s.get('api_key') != env_key:
    probe('https://fapi.binance.com', env_key, env_sec, 'mainnet_env_only')
    probe('https://testnet.binancefuture.com', env_key, env_sec, 'testnet_env_only')
    probe('https://fapi.binance.com', s['api_key'], s['api_secret'], 'mainnet_session_only')
    probe('https://testnet.binancefuture.com', s['api_key'], s['api_secret'], 'testnet_session_only')

# VPS public IP (for Binance key whitelist)
try:
    ip=urllib.request.urlopen('https://api.ipify.org', timeout=5).read().decode()
    print('vps_public_ip', ip)
except Exception as e:
    print('ipify_fail', e)
PY
'''

def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print(err.encode("ascii", "replace").decode("ascii")[-2000:])
    c.close()

if __name__ == "__main__":
    main()
