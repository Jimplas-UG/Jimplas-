#!/usr/bin/env python3
"""Halt new live entries on FRA — SCANNER_EXEC=0 + FORWARD_DRY_RUN=1. Leaves open positions alone."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set -euo pipefail
python3 - <<'PY'
from pathlib import Path
p = Path('/etc/bilshenz.env')
lines = p.read_text().splitlines()
out = []
seen = set()
for line in lines:
    if not line.strip() or line.strip().startswith('#') or '=' not in line:
        out.append(line)
        continue
    k = line.split('=', 1)[0].strip()
    if k == 'SCANNER_EXEC':
        out.append('SCANNER_EXEC=0'); seen.add(k)
    elif k == 'FORWARD_DRY_RUN':
        out.append('FORWARD_DRY_RUN=1'); seen.add(k)
    else:
        out.append(line); seen.add(k)
if 'SCANNER_EXEC' not in seen:
    out.append('SCANNER_EXEC=0')
if 'FORWARD_DRY_RUN' not in seen:
    out.append('FORWARD_DRY_RUN=1')
p.write_text('\n'.join(out) + '\n')
print('HALTED SCANNER_EXEC=0 FORWARD_DRY_RUN=1')
PY

# Persist emergency stop in scanner risk so UI + runtime both show halted.
python3 - <<'PY'
import json
from pathlib import Path
for cand in (
    Path('/var/lib/bilshenz/scanner-risk.json'),
    Path('/var/lib/bilshenz/risk.json'),
    Path('/opt/bilshenz/binance_trading_system/python/data/scanner-risk.json'),
):
    if not cand.exists():
        continue
    try:
        raw = json.loads(cand.read_text() or '{}')
    except Exception:
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    raw['exec_halted'] = True
    cand.write_text(json.dumps(raw, indent=2) + '\n')
    print('risk_halted', cand)
PY

systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 5
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
grep -E '^(SCANNER_EXEC|FORWARD_DRY_RUN)=' /etc/bilshenz.env
curl -sS -m 8 http://127.0.0.1:8766/health > /tmp/h.json
python3 - <<'PY'
import json
h = json.load(open('/tmp/h.json'))
sc = h.get('scanner') or {}
print('mode', h.get('mode'), 'connected', h.get('connected'))
print('can_execute', sc.get('can_execute'), 'exec_block', sc.get('exec_block'))
print('exec_enabled', sc.get('exec_enabled'), 'user_exec_halted', sc.get('user_exec_halted'))
print('active_symbol', sc.get('active_symbol'))
print('last_exec_error', sc.get('last_exec_error'))
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err.encode("ascii", "replace").decode("ascii")[-2000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
