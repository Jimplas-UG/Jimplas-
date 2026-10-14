#!/usr/bin/env python3
"""Why /health returns 500 + WS accept from localhost."""
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
echo '=== health body ==='
curl -sS -m 8 -w '\nHTTP %{http_code}\n' http://127.0.0.1:8766/health | tail -n 40
echo '=== errors.log tail ==='
tail -n 40 /var/log/bilshenz/errors.log 2>/dev/null
echo '=== binance-api.log health/traceback ==='
grep -hE 'health|Traceback|/ws/|WebSocket|Exception' /var/log/bilshenz/binance-api.log 2>/dev/null | tail -n 40
echo '=== ban file ==='
cat /var/lib/bilshenz/rest-ban.json 2>/dev/null; echo
date -u +%Y-%m-%dT%H:%M:%SZ
echo '=== process ==='
ps -o pid,etimes,pcpu,rss,args -p $(pgrep -f 'python main.py' | head -1) 2>/dev/null
echo '=== local ws probe ==='
python3 - <<'PY'
import asyncio, json
try:
    import websockets
except ImportError:
    print('no websockets lib')
    raise SystemExit(0)

async def main():
    tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
    url=f'ws://127.0.0.1:8766/ws/scanner?token={tok}'
    try:
        async with websockets.connect(url, open_timeout=5, close_timeout=2) as ws:
            msg=await asyncio.wait_for(ws.recv(), timeout=8)
            print('WS_OK', str(msg)[:180])
    except Exception as e:
        print('WS_FAIL', type(e).__name__, e)

asyncio.run(main())
PY
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err[-800:])
    c.close()


if __name__ == "__main__":
    main()
