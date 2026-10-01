#!/usr/bin/env python3
"""Deploy Binance WS URL migration (/public /market /private) — no strategy changes."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE_PY = "/opt/bilshenz/binance_trading_system/python"
PY = f"{REMOTE_PY}/.venv/bin/python"
FILES = [
    "scanner_stream.py",
    "tick_stream.py",
    "user_data_stream.py",
]

CMD = rf"""
set -euo pipefail
{PY} -m py_compile \
  {REMOTE_PY}/scanner_stream.py \
  {REMOTE_PY}/tick_stream.py \
  {REMOTE_PY}/user_data_stream.py
systemctl restart bilshenz-binance-api
sleep 4
systemctl is-active bilshenz-binance-api
# wait streams up
for i in 1 2 3 4 5 6 7 8; do
  sleep 1
  curl -sS -m 3 http://127.0.0.1:8766/health >/tmp/h.json || continue
  {PY} - <<'PY'
import json
h=json.load(open('/tmp/h.json'))
sc=h.get('scanner_stream') or {{}}
tk=h.get('tick_stream') or {{}}
ud=h.get('user_data_stream') or {{}}
print('connected', h.get('connected'), 'testnet', h.get('testnet'))
print('tick_ws', tk.get('ws_connected'), 'err', tk.get('last_error'))
print('scanner_ws', sc.get('ws_connected'), 'rest_active', sc.get('rest_active'),
      'ws_ticks', sc.get('ws_ticks'), 'rest_ticks', sc.get('rest_ticks'), 'err', sc.get('last_error'))
print('user_ws', ud.get('ws_connected'), 'listen', ud.get('listen_key_active'), 'err', ud.get('last_error'),
      'events', ud.get('events_received'))
PY
  # Prefer WS live (rest_active false) once warm
  rest=$({PY} -c "import json; print((json.load(open('/tmp/h.json')).get('scanner_stream') or {{}}).get('rest_active'))")
  wsc=$({PY} -c "import json; print((json.load(open('/tmp/h.json')).get('scanner_stream') or {{}}).get('ws_connected'))")
  if [ "$wsc" = "True" ] && [ "$rest" = "False" ]; then
    echo 'SCANNER_WS_LIVE'
    break
  fi
done
# live compare: new market vs legacy miniTicker from venv
{PY} - <<'PY'
import asyncio, json, time
import websockets

async def probe(url, secs=3.0):
    n=0; first=None; err=None
    t0=time.monotonic()
    try:
        async with websockets.connect(url, ping_interval=8, ping_timeout=12, open_timeout=8) as ws:
            while time.monotonic()-t0 < secs:
                try:
                    await asyncio.wait_for(ws.recv(), timeout=1.0)
                    n+=1
                    if first is None: first=round(time.monotonic()-t0,3)
                except asyncio.TimeoutError:
                    continue
    except Exception as e:
        err=str(e)[:160]
    return {{"url":url,"msgs":n,"first_s":first,"err":err}}

async def main():
    urls=[
        "wss://fstream.binance.com/ws/!miniTicker@arr",
        "wss://fstream.binance.com/market/ws/!miniTicker@arr",
        "wss://fstream.binance.com/public/ws/btcusdt@bookTicker",
        "wss://fstream.binance.com/ws/btcusdt@bookTicker",
    ]
    out=[await probe(u) for u in urls]
    print(json.dumps(out, indent=2))

asyncio.run(main())
PY
# journal snippet
journalctl -u bilshenz-binance-api --since '30 seconds ago' --no-pager | grep -iE 'scanner|tick stream|user data|connecting|silent|REST' | tail -40
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for name in FILES:
        local = ROOT / "binance_trading_system" / "python" / name
        print(f"upload {name}")
        sftp.put(str(local), f"{REMOTE_PY}/{name}")
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=120)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-4000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
