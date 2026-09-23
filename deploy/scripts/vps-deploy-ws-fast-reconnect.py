#!/usr/bin/env python3
"""Deploy WS speed + fail-fast REST cool-down to FRA."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE_PY = "/opt/bilshenz/binance_trading_system/python"
FILES = [
    "scanner_stream.py",
    "tick_stream.py",
    "user_data_stream.py",
    "binance_connector.py",
    "main.py",
    "position_manager.py",
]

CMD = r"""
set -euo pipefail
/opt/bilshenz/binance_trading_system/python/.venv/bin/python -m py_compile \
  /opt/bilshenz/binance_trading_system/python/scanner_stream.py \
  /opt/bilshenz/binance_trading_system/python/tick_stream.py \
  /opt/bilshenz/binance_trading_system/python/user_data_stream.py \
  /opt/bilshenz/binance_trading_system/python/binance_connector.py \
  /opt/bilshenz/binance_trading_system/python/main.py \
  /opt/bilshenz/binance_trading_system/python/position_manager.py
systemctl restart bilshenz-binance-api
sleep 3
systemctl is-active bilshenz-binance-api
# health must return in <1s now
START=$(date +%s%3N)
CODE=$(curl -sS -m 3 -o /tmp/h.json -w '%{http_code}' http://127.0.0.1:8766/health || echo FAIL)
END=$(date +%s%3N)
echo "health_http=$CODE ms=$((END-START))"
python3 - <<'PY'
import json, time, urllib.request
t0=time.perf_counter()
with urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=3) as r:
    h=json.loads(r.read().decode())
print(f"health2_ms={(time.perf_counter()-t0)*1000:.0f} ok={h.get('ok')} connected={h.get('connected')} rest_cool_s={h.get('rest_cool_s')}")
print('scanner_ws', (h.get('scanner_stream') or {}).get('ws_connected'))
print('tick_ws', (h.get('tick_stream') or {}).get('ws_connected'))
PY
# WS reconnect timing via stdlib
python3 - <<'PY'
import json, time, threading, urllib.request
from websocket import create_connection
# fallback: raw websocket handshake without third-party if needed
try:
    from websocket import create_connection as cw
except Exception:
    cw=None

# parse token
tok=''
for line in open('/etc/bilshenz.env'):
    if line.startswith('BRIDGE_TOKEN='):
        tok=line.split('=',1)[1].strip().strip('"').strip("'")
        break
url=f'ws://127.0.0.1:8766/ws/scanner?token={tok}'

def once(label):
    import struct, hashlib, base64, os, socket
    t0=time.perf_counter()
    key=base64.b64encode(os.urandom(16)).decode()
    host, path = '127.0.0.1', f'/ws/scanner?token={tok}'
    s=socket.create_connection(('127.0.0.1',8766), timeout=5)
    s.settimeout(5)
    req=(
        f'GET {path} HTTP/1.1\r\n'
        f'Host: {host}:8766\r\n'
        'Upgrade: websocket\r\n'
        'Connection: Upgrade\r\n'
        f'Sec-WebSocket-Key: {key}\r\n'
        'Sec-WebSocket-Version: 13\r\n\r\n'
    )
    s.sendall(req.encode())
    buf=b''
    while b'\r\n\r\n' not in buf:
        chunk=s.recv(4096)
        if not chunk:
            break
        buf+=chunk
    if b'101' not in buf.split(b'\r\n',1)[0]:
        print(label, 'handshake_fail', buf[:120])
        s.close()
        return
    # read one frame
    hdr=s.recv(2)
    if len(hdr)<2:
        print(label, 'no_frame')
        s.close(); return
    ln=hdr[1] & 0x7f
    if ln==126:
        ext=s.recv(2); ln=int.from_bytes(ext,'big')
    elif ln==127:
        ext=s.recv(8); ln=int.from_bytes(ext,'big')
    data=b''
    while len(data)<ln:
        data+=s.recv(ln-len(data))
    try:
        msg=json.loads(data.decode())
        typ=msg.get('type')
    except Exception:
        typ='?'
    ms=(time.perf_counter()-t0)*1000
    print(f'{label}_ms={ms:.0f} type={typ}')
    s.close()

once('connect1')
t0=time.perf_counter()
once('reconnect')
print(f'gap_ms={(time.perf_counter()-t0)*1000:.0f}')
PY
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
    _, o, e = c.exec_command(CMD, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-3000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
