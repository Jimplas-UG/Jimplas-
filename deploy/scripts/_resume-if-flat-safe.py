#!/usr/bin/env python3
"""Resume scanner entries only when exchange flat + no stuck/oversize (post-deploy)."""
from pathlib import Path
import json
import urllib.request
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set -e
TOK=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
PY=/opt/bilshenz/binance_trading_system/python/.venv/bin/python
# Gate: must be flat, no stuck, no oversize
curl -sS -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/positions > /tmp/pos.json
curl -sS http://127.0.0.1:8766/health > /tmp/health.json
$PY - <<'PY'
import json
pos=json.load(open('/tmp/pos.json'))
h=json.load(open('/tmp/health.json'))
sc=h.get('scanner') or {}
open_n=len([p for p in (pos.get('positions') or []) if abs(float(p.get('volume') or p.get('positionAmt') or 0))>1e-12])
stuck=sc.get('stuck_close_symbols') or []
over=sc.get('oversize_external_symbols') or []
print('gate open', open_n, 'stuck', stuck, 'over', over)
assert open_n==0, open_n
assert not stuck, stuck
assert not over, over
print('RESUME_GATE_OK')
PY
curl -sS -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"enabled":true}' http://127.0.0.1:8766/api/scanner/exec
echo
curl -sS http://127.0.0.1:8766/health | $PY -c "import sys,json; h=json.load(sys.stdin); sc=h.get('scanner') or {}; print('AFTER can',sc.get('can_execute'),'halt',sc.get('user_exec_halted'),'safe',sc.get('safe_mode'))"
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=45)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err.encode("ascii", "replace").decode("ascii")[-800:])
    c.close()


if __name__ == "__main__":
    main()
