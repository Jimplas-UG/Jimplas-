#!/usr/bin/env python3
"""HALT new scanner entries on FRA + deploy diagnostics non-blocking fix. No strategy edits."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE_PY = "/opt/bilshenz/binance_trading_system/python"
PY = f"{REMOTE_PY}/.venv/bin/python"

CMD = rf"""
set -euo pipefail
# Kill-switch: phone uninstall does NOT stop VPS bot — arm off now.
python3 - <<'PY'
from pathlib import Path
p=Path('/etc/bilshenz.env')
lines=p.read_text().splitlines()
out=[]
seen=set()
for line in lines:
    if not line.strip() or line.strip().startswith('#') or '=' not in line:
        out.append(line); continue
    k=line.split('=',1)[0].strip()
    if k=='SCANNER_EXEC':
        out.append('SCANNER_EXEC=0'); seen.add(k)
    elif k=='FORWARD_DRY_RUN':
        out.append('FORWARD_DRY_RUN=1'); seen.add(k)
    else:
        out.append(line); seen.add(k)
if 'SCANNER_EXEC' not in seen: out.append('SCANNER_EXEC=0')
if 'FORWARD_DRY_RUN' not in seen: out.append('FORWARD_DRY_RUN=1')
p.write_text('\\n'.join(out)+'\\n')
print('HALTED SCANNER_EXEC=0 FORWARD_DRY_RUN=1')
PY
{PY} -m py_compile {REMOTE_PY}/main.py
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 4
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
grep -E '^(SCANNER_EXEC|FORWARD_DRY_RUN)=' /etc/bilshenz.env
# verify halt + streams + flat
curl -sS -m 6 http://127.0.0.1:8766/health > /tmp/h.json
TOK=$(grep '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS -m 8 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/diagnostics > /tmp/d.json
curl -sS -m 8 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/positions > /tmp/p.json
{PY} - <<'PY'
import json, time
t0=time.perf_counter()
h=json.load(open('/tmp/h.json'))
d=json.load(open('/tmp/d.json'))
p=json.load(open('/tmp/p.json'))
print('diag_ms', round((time.perf_counter()-t0)*1000,1))
sc=h.get('scanner') or {{}}
print('scanner_can_execute', sc.get('can_execute'), 'block', sc.get('exec_block'), 'exec_enabled', sc.get('exec_enabled'))
print('streams', 'tick', (h.get('tick_stream') or {{}}).get('ws_connected'),
      'scanner', (h.get('scanner_stream') or {{}}).get('ws_connected'),
      'user', (h.get('user_data_stream') or {{}}).get('ws_connected'))
print('diag_ws_user', (d.get('user_data_stream') or {{}}).get('ws_connected'),
      'diag_ws_scanner', (d.get('scanner_stream') or {{}}).get('ws_connected'),
      'diag_ok', d.get('ok'), 'binance_ms', d.get('binance_latency_ms'))
pos=p.get('positions') if isinstance(p, dict) else p
print('open_positions', len(pos) if isinstance(pos, list) else pos)
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    sftp.put(str(ROOT / "binance_trading_system/python/main.py"), f"{REMOTE_PY}/main.py")
    sftp.put(
        str(ROOT / "frontend/components/DiagnosticsPanel.js"),
        "/opt/bilshenz/frontend/components/DiagnosticsPanel.js",
    )
    sftp.close()
    print("uploaded main.py + DiagnosticsPanel.js")
    _, o, e = c.exec_command(CMD, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err.encode("ascii", "replace").decode("ascii")[-2500:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
