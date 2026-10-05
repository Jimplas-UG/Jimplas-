#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
echo TOKEN_LEN=${#TOKEN}
timeout 8 curl -v -m 6 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health 2>&1 | tail -40
echo '---'
ss -lntp | grep -E '8766|8791' || true
echo '---'
tail -n 40 /var/log/bilshenz/binance-api.log
echo '---'
python3 - <<'PY'
import asyncio, json, time
from pathlib import Path
import websockets
env=Path('/etc/bilshenz.env').read_text()
token=[l.split('=',1)[1].strip().strip('"').strip("'") for l in env.splitlines() if l.startswith('BRIDGE_TOKEN=')][0]
url=f'ws://127.0.0.1:8766/ws/scanner?token={token}'
async def main():
    t0=time.perf_counter()
    try:
        async with websockets.connect(url, open_timeout=5, close_timeout=1, ping_interval=None) as ws:
            print('opened', round((time.perf_counter()-t0)*1000), 'ms')
            for i in range(4):
                raw=await asyncio.wait_for(ws.recv(), timeout=3)
                m=json.loads(raw)
                print('msg', i, m.get('type'), 'keys', list(m)[:6])
    except Exception as e:
        print('WSERR', type(e).__name__, e)
asyncio.run(main())
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=45)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
