#!/usr/bin/env python3
"""Inspect live scanner coin states for NIL/BOB after manual close."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
import json, urllib.request

# Import live process state via HTTP only — also dump coin statuses from a small probe endpoint if any.
tok = open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
H = {'Authorization': 'Bearer ' + tok}

def get(url):
    req = urllib.request.Request(url, headers=H)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

h = json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc = h.get('scanner') or {}
print('active_strategies', sc.get('active_strategies'), 'watchlist', sc.get('watchlist'), 'active', sc.get('active_symbol'))
print('rule_halt', sc.get('rule_kernel'))

# Try debug endpoints
for path in ('/api/debug/scanner', '/api/scanner/coins', '/api/debug/coins', '/health'):
    try:
        d = get('http://127.0.0.1:8766'+path) if path != '/health' else h
        # search nested for BOB/NIL
        raw = json.dumps(d, default=str)
        if 'NIL' in raw or 'BOB' in raw:
            print('FOUND in', path, 'len', len(raw))
    except Exception as e:
        print(path, type(e).__name__)

# Direct in-process inspect via systemd MainPID? Use gdb? No — use a small API call if main exposes snapshot.
# Fall back: ask positions force + check open orders
pos = get('http://127.0.0.1:8766/api/positions')
print('pos_count', len(pos.get('positions') or []))
try:
    oo = get('http://127.0.0.1:8766/api/open-orders')
    print('open_orders', oo)
except Exception as e:
    print('open_orders_skip', e)

# Check if BOB still has TP/SL orders hanging
try:
    st = get('http://127.0.0.1:8766/api/status')
    print('status_keys', list(st.keys())[:30])
    if 'open_orders' in st:
        print('st_open_orders', st.get('open_orders'))
except Exception as e:
    print('status_err', e)
PY

# In-process dump via python attaching to running module isn't available; use journal for NIL manage
echo '=== NIL manage last 30m ==='
grep -E 'NILUSDT|1000000BOBUSDT' /var/log/bilshenz/app.log | tail -n 40
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, stdout, stderr = client.exec_command(CMD, timeout=90)
    sys.stdout.write(stdout.read().decode("utf-8", "replace"))
    err = stderr.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-1500:])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
