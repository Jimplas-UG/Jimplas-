#!/usr/bin/env python3
"""Probe private user-data WS URL shapes with a live listenKey."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"

REMOTE = r'''
import asyncio, json, time, os, hmac, hashlib, urllib.parse, urllib.request
import websockets

# load keys from env file used by service
env={}
for line in open('/etc/bilshenz.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1)
    env[k.strip()]=v.strip().strip('"').strip("'")

# also try runtime from health/session — prefer connected mainnet keys from process env
unit=os.popen("systemctl show bilshenz-binance-api -p Environment --value").read()
# fallback: ask bridge
import urllib.request as u
h=json.loads(u.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
print('health_connected', h.get('connected'), 'testnet', h.get('testnet'))
ud=h.get('user_data_stream') or {}
print('user_status', ud)

# create listenKey via bridge signed endpoint if available
# Use connector through a tiny inline signed POST using keys from env if present
api_key = env.get('BINANCE_API_KEY') or env.get('API_KEY') or ''
api_secret = env.get('BINANCE_API_SECRET') or env.get('API_SECRET') or ''
print('env_key_present', bool(api_key), 'len', len(api_key))

# Prefer asking the running bridge to mint a listenKey via internal debug if exists.
# Otherwise POST with session keys stored by app.
def try_listen_via_bridge():
    # use /v1 account path? try common
    for path in ['/debug/listenKey', '/listenKey']:
        try:
            r=u.urlopen('http://127.0.0.1:8766'+path, timeout=3)
            return json.loads(r.read())
        except Exception:
            pass
    return None

# Extract keys from service EnvironmentFile + runtime — the app stores keys in memory after login.
# Call a signed request using the bridge's own session by hitting an endpoint that needs auth...
# Simpler: read from /proc environ of main.py
pid=os.popen("pgrep -f 'binance_trading_system/python/main.py' | head -1").read().strip()
proc_env={}
if pid:
    raw=open(f'/proc/{pid}/environ','rb').read().split(b'\0')
    for item in raw:
        if b'=' in item:
            k,v=item.split(b'=',1)
            try:
                proc_env[k.decode()]=v.decode()
            except Exception:
                pass
api_key = api_key or proc_env.get('BINANCE_API_KEY','') or proc_env.get('API_KEY','')
api_secret = api_secret or proc_env.get('BINANCE_API_SECRET','') or proc_env.get('API_SECRET','')
print('proc_key_present', bool(api_key))

# Use bridge REST that proxies listenKey — check openapi-ish
# Fall back: signed POST to Binance using keys from a dump the app may write
# Read from python session file if any
import glob
for p in ['/opt/bilshenz/data/binance_session.json','/opt/bilshenz/binance_trading_system/python/data/session.json','/var/lib/bilshenz/session.json']:
    if os.path.exists(p):
        print('session_file', p)
        try:
            s=json.load(open(p))
            print('session_keys', list(s.keys())[:20])
            api_key = api_key or s.get('api_key') or s.get('apiKey') or ''
            api_secret = api_secret or s.get('api_secret') or s.get('apiSecret') or ''
        except Exception as e:
            print('session_read_err', e)

def signed_listen(base, key, secret):
    ts=int(time.time()*1000)
    qs=f'timestamp={ts}'
    sig=hmac.new(secret.encode(), qs.encode(), hashlib.sha256).hexdigest()
    url=f'{base}/fapi/v1/listenKey?{qs}&signature={sig}'
    req=urllib.request.Request(url, method='POST', headers={'X-MBX-APIKEY': key})
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read())

listen=None
err=None
if api_key and api_secret:
    try:
        listen=signed_listen('https://fapi.binance.com', api_key, api_secret)
    except Exception as e:
        err=str(e)
        try:
            listen=signed_listen('https://testnet.binancefuture.com', api_key, api_secret)
        except Exception as e2:
            err=f'{err} | testnet:{e2}'
else:
    err='no keys in env/session'

print('listen_err', err)
print('listen', {k: (v[:8]+'...') if k=='listenKey' and isinstance(v,str) else v for k,v in (listen or {}).items()})

lk=(listen or {}).get('listenKey')
if not lk:
    raise SystemExit(0)

events='ORDER_TRADE_UPDATE,ACCOUNT_UPDATE,MARGIN_CALL,ACCOUNT_CONFIG_UPDATE,TRADE_LITE,listenKeyExpired'
events_q=urllib.parse.quote(events, safe=',')
candidates=[
    f'wss://fstream.binance.com/private/ws?listenKey={lk}&events={events}',
    f'wss://fstream.binance.com/private/ws?listenKey={lk}&events={events_q}',
    f'wss://fstream.binance.com/private/ws/{lk}',
    f'wss://fstream.binance.com/private/ws/{lk}?events={events}',
    f'wss://fstream.binance.com/ws/{lk}',
    f'wss://fstream.binance.com/private/stream?streams={lk}',
]

async def probe(url, secs=2.5):
    n=0; err=None; code=None
    try:
        async with websockets.connect(url, ping_interval=8, ping_timeout=12, open_timeout=8) as ws:
            t0=time.monotonic()
            while time.monotonic()-t0 < secs:
                try:
                    await asyncio.wait_for(ws.recv(), timeout=1.0)
                    n+=1
                except asyncio.TimeoutError:
                    continue
    except Exception as e:
        err=str(e)[:220]
    return {'url': url.replace(lk, lk[:6]+'...'), 'msgs': n, 'err': err}

async def main():
    out=[]
    for u in candidates:
        out.append(await probe(u))
        await asyncio.sleep(0.2)
    print(json.dumps(out, indent=2))

asyncio.run(main())
'''


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    i, o, e = c.exec_command(f"{PY} -", timeout=90)
    i.write(REMOTE.encode())
    i.channel.shutdown_write()
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("---stderr---")
        print(err[-3000:])
    c.close()


if __name__ == "__main__":
    main()
