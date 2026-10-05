#!/usr/bin/env python3
"""Verify WS fast reconnect on FRA after deploy."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set -euo pipefail
echo '=== service ==='
systemctl is-active bilshenz-binance-api || true
systemctl show bilshenz-binance-api -p MainPID -p FragmentPath --no-pager || true
echo '=== constants on disk ==='
grep -nE 'RECONNECT_MAX_SEC|CLIENT_HB_SEC|ping_timeout' /opt/bilshenz/binance_trading_system/python/scanner_stream.py | head -20
echo '=== how bridge starts ==='
systemctl cat bilshenz-binance-api | head -40
echo '=== health ==='
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS -m 5 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health | python3 -c 'import sys,json; h=json.load(sys.stdin); print({k:h.get(k) for k in ("ok","connected","testnet","paper")}); print("streams", h.get("streams"))'
echo '=== ws smoke ==='
python3 - <<'PY'
import asyncio, json, time
from pathlib import Path
try:
    import websockets
except Exception as e:
    print('websockets import fail', e)
    raise SystemExit(0)
env=Path('/etc/bilshenz.env').read_text()
token=[l.split('=',1)[1].strip().strip('"').strip("'") for l in env.splitlines() if l.startswith('BRIDGE_TOKEN=')][0]
url=f'ws://127.0.0.1:8766/ws/scanner?token={token}'

async def once(label):
    t0=time.perf_counter()
    async with websockets.connect(url, open_timeout=5, close_timeout=1, ping_interval=None) as ws:
        types=[]
        deadline=time.perf_counter()+5
        while time.perf_counter()<deadline:
            raw=await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline-time.perf_counter()))
            m=json.loads(raw)
            types.append(m.get('type'))
            if 'hb' in types and 'snapshot' in types:
                break
            if types and types[0]=='hb':
                break
        ms=(time.perf_counter()-t0)*1000
        print(f'{label}_ms={ms:.0f} types={types[:4]}')

async def main():
    await once('connect1')
    t0=time.perf_counter()
    await once('reconnect')
    print(f'gap_ms={(time.perf_counter()-t0)*1000:.0f}')

asyncio.run(main())
PY
echo '=== recent logs ==='
tail -n 25 /var/log/bilshenz/app.log 2>/dev/null || journalctl -u bilshenz-binance-api -n 25 --no-pager
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-3000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
