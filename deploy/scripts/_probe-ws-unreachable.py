#!/usr/bin/env python3
"""Diagnose WebSocket unreachable: health, stream state, recent logs, listening ports."""
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set -e
echo '=== services ==='
systemctl is-active bilshenz-binance-api bilshenz-forward-bot bilshenz-desk-api 2>/dev/null || true
echo '=== listen ports ==='
ss -tlnp | grep -E '8766|8791|3000|8080|443|80' || true
echo '=== health ==='
python3 - <<'PY'
import json, urllib.request
try:
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
except Exception as e:
    print('HEALTH_FAIL', e)
    raise SystemExit(0)
sc=h.get('scanner') or {}
print('mode', h.get('mode'), 'conn', h.get('connected'), 'cool', h.get('rest_cool_s'))
print('can', sc.get('can_execute'), 'block', sc.get('exec_block') or sc.get('exec_block_reason'))
print('scanner', {k: sc.get(k) for k in ('enabled','exec_enabled','symbols_tracked','watchlist','active_symbol')})
for k in ('scanner_stream','tick_stream','user_stream','user_data_stream','ws','streams'):
    if k in h:
        print(k, json.dumps(h[k])[:500])
# nested
for k,v in h.items():
    if isinstance(v, dict) and any(x in k.lower() for x in ('stream','ws','tick','user')):
        print('KEY', k, json.dumps(v)[:600])
PY
echo '=== recent WS / unreachable lines ==='
since=$(date -u -d '-6 hours' +%Y-%m-%dT%H:%M 2>/dev/null || date -u -v-6H +%Y-%m-%dT%H:%M)
grep -hE 'unreachable|WebSocket|websocket|ws_connected|scanner stream|USER_WS|tick stream|keepalive|1011|1006|Connection refused|failed to connect|ECONNREFUSED|disconnect' /var/log/bilshenz/*.log 2>/dev/null | awk -v s="$since" '$1 >= s' | tail -n 60
echo '=== bridge journal last 30 ==='
journalctl -u bilshenz-binance-api --no-pager -n 30 2>/dev/null | cut -c1-220
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
