#!/usr/bin/env python3
"""Hot-fix user stream event list + verify all three Binance WS feeds live."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE_PY = "/opt/bilshenz/binance_trading_system/python"
PY = f"{REMOTE_PY}/.venv/bin/python"

CMD = rf"""
set -euo pipefail
{PY} -m py_compile {REMOTE_PY}/user_data_stream.py
systemctl restart bilshenz-binance-api
sleep 5
for i in 1 2 3 4 5 6 7 8 9 10; do
  curl -sS -m 4 http://127.0.0.1:8766/health >/tmp/h.json || {{ sleep 1; continue; }}
  {PY} - <<'PY'
import json
h=json.load(open('/tmp/h.json'))
sc=h.get('scanner_stream') or {{}}
tk=h.get('tick_stream') or {{}}
ud=h.get('user_data_stream') or {{}}
ok = (
  bool(tk.get('ws_connected'))
  and bool(sc.get('ws_connected'))
  and not bool(sc.get('rest_active'))
  and bool(ud.get('ws_connected'))
)
print('tick', tk.get('ws_connected'), 'scanner_ws', sc.get('ws_connected'),
      'rest_active', sc.get('rest_active'), 'ws_ticks', sc.get('ws_ticks'),
      'user', ud.get('ws_connected'), 'err', ud.get('last_error'))
print('SYNC_OK' if ok else 'SYNC_WAIT')
PY
  grep -q SYNC_OK /tmp/h.json 2>/dev/null || true
  if {PY} -c "import json;h=json.load(open('/tmp/h.json'));sc=h.get('scanner_stream') or {{}};ud=h.get('user_data_stream') or {{}};tk=h.get('tick_stream') or {{}};import sys;sys.exit(0 if (tk.get('ws_connected') and sc.get('ws_connected') and not sc.get('rest_active') and ud.get('ws_connected')) else 1)"; then
    echo ALL_STREAMS_LIVE
    break
  fi
  sleep 1
done
# lag sample: compare REST BTC vs cached tick age via health symbols
{PY} - <<'PY'
import json, time, urllib.request
h=json.load(open('/tmp/h.json'))
print('health_summary', {{
  'connected': h.get('connected'),
  'cool': h.get('rest_cool_s'),
  'tick': h.get('tick_stream'),
  'scanner': {{k:(h.get('scanner_stream') or {{}}).get(k) for k in ('ws_connected','rest_active','ws_ticks','rest_ticks','last_error','clients')}},
  'user': h.get('user_data_stream'),
}})
t0=time.time()
with urllib.request.urlopen('https://fapi.binance.com/fapi/v1/ticker/bookTicker?symbol=BTCUSDT', timeout=5) as r:
    book=json.loads(r.read())
print('binance_book', book, 'rtt_ms', round((time.time()-t0)*1000,1))
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    sftp.put(str(ROOT / "binance_trading_system/python/user_data_stream.py"), f"{REMOTE_PY}/user_data_stream.py")
    # frontend silence fix for any hosted web bundle that re-bundles later
    try:
        sftp.put(str(ROOT / "frontend/lib/wsReconnect.js"), "/opt/bilshenz/frontend/lib/wsReconnect.js")
        print("upload frontend/lib/wsReconnect.js")
    except Exception as e:
        print("frontend upload skip", e)
    sftp.close()
    print("upload user_data_stream.py")
    _, o, e = c.exec_command(CMD, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-3000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
