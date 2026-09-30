#!/usr/bin/env python3
"""Verify fast login on FRA after deploy."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
python3 - <<'PY'
import json, time, urllib.request
from pathlib import Path
d={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
    if '=' in l and not l.startswith('#'):
        k,v=l.split('=',1); d[k]=v.strip().strip('"').strip("'")
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read().decode())
print('health', h.get('mode'), 'connected', h.get('connected'), 'cool', h.get('rest_cool_s'))
key=d.get('BINANCE_API_KEY',''); secret=d.get('BINANCE_API_SECRET',''); tok=d.get('BRIDGE_TOKEN','')
body=json.dumps({'api_key':key,'api_secret':secret,'testnet':True,'auto_detect_env':True}).encode()
req=urllib.request.Request('http://127.0.0.1:8766/api/login', data=body, method='POST',
    headers={'Content-Type':'application/json','X-Bridge-Token':tok})
t0=time.perf_counter()
with urllib.request.urlopen(req, timeout=20) as r:
    out=json.loads(r.read().decode())
ms=(time.perf_counter()-t0)*1000
print('LOGIN_MS', round(ms), 'ok', out.get('ok'), 'mode', out.get('mode'))
src=Path('/opt/bilshenz/binance_trading_system/python/main.py').read_text()
uds=Path('/opt/bilshenz/binance_trading_system/python/user_data_stream.py').read_text()
print('patch_main', '_post_login_stream_refresh' in src)
print('patch_uds', 'asyncio.wait_for' in uds)
assert out.get('ok') is True and ms < 8000
print('LOGIN_SPEED_OK')
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-800:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
