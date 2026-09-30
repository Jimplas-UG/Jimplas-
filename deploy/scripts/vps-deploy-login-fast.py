#!/usr/bin/env python3
"""Deploy fast /api/login (non-blocking stream refresh) to FRA."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

FILES = [
    "binance_trading_system/python/main.py",
]

CMD = r"""
set -euo pipefail
systemctl restart bilshenz-binance-api
sleep 8
systemctl is-active bilshenz-binance-api
TOKEN=$(python3 -c "from pathlib import Path; d={};
[d.__setitem__(a,b.strip().strip(chr(34)).strip(chr(39))) for a,b in (l.split('=',1) for l in Path('/etc/bilshenz.env').read_text().splitlines() if '=' in l and not l.startswith('#'))];
print(d.get('BRIDGE_TOKEN',''))")
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health | python3 -c "import sys,json;d=json.load(sys.stdin);s=d.get('scanner') or {};print('mode',d.get('mode'),'connected',d.get('connected'),'exec',s.get('can_execute'))"
python3 - <<'PY'
import inspect
from pathlib import Path
src = Path('/opt/bilshenz/binance_trading_system/python/main.py').read_text(encoding='utf-8')
assert '_post_login_stream_refresh' in src
assert 'Never await stream stop/start here' in src
assert 'bg_stream=' in src
print('LOGIN_FAST_OK')
PY
# Timed login against already-live env session (should be << 5s now)
python3 - <<'PY'
import json, time, urllib.request
from pathlib import Path
d={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
    if '=' in l and not l.startswith('#'):
        k,v=l.split('=',1); d[k]=v.strip().strip('"').strip("'")
key=d.get('BINANCE_API_KEY',''); secret=d.get('BINANCE_API_SECRET',''); tok=d.get('BRIDGE_TOKEN','')
assert key and secret, 'missing env keys'
body=json.dumps({'api_key':key,'api_secret':secret,'testnet':True,'auto_detect_env':True}).encode()
req=urllib.request.Request('http://127.0.0.1:8766/api/login', data=body, method='POST',
    headers={'Content-Type':'application/json','X-Bridge-Token':tok})
t0=time.perf_counter()
with urllib.request.urlopen(req, timeout=20) as r:
    out=json.loads(r.read().decode())
ms=(time.perf_counter()-t0)*1000
print('LOGIN_MS', round(ms), 'ok', out.get('ok'), 'mode', out.get('mode'), 'can_execute', out.get('can_execute'))
assert out.get('ok') is True
assert ms < 8000, f'login still too slow: {ms:.0f}ms'
print('LOGIN_SPEED_OK')
PY
"""


def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in FILES:
        local = ROOT / rel.replace("/", "\\")
        print("upload", rel)
        sftp.put(str(local), f"/opt/bilshenz/{rel}")
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=120)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-1500:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
