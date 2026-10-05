#!/usr/bin/env python3
"""Flip Bilshenz bridge to Binance Futures TESTNET and verify."""
from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path

import paramiko

HOST = os.environ.get("VPS_HOST", "159.223.29.223")
KEY = Path.home() / ".ssh" / "id_ed25519"
ENABLE = os.environ.get("TESTNET", "1").strip() in ("1", "true", "yes")


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)

    testnet = "1" if ENABLE else "0"
    cmd = rf"""
set -euo pipefail
ENVF=/etc/bilshenz.env
python3 - <<'PY'
from pathlib import Path
p = Path('/etc/bilshenz.env')
want = {{
  'BINANCE_TESTNET': '{testnet}',
  'BINANCE_PAPER': '0',
  'FORWARD_DRY_RUN': '0',
  'SCANNER_EXEC': '1',
}}
lines = p.read_text().splitlines()
out, seen = [], set()
for line in lines:
    if '=' in line and not line.startswith('#'):
        k = line.split('=', 1)[0]
        if k in want:
            out.append(f'{{k}}={{want[k]}}')
            seen.add(k)
            continue
    out.append(line)
for k, v in want.items():
    if k not in seen:
        out.append(f'{{k}}={{v}}')
p.write_text('\\n'.join(out) + '\\n')
p.chmod(0o600)
print('BINANCE_TESTNET={testnet}')
PY
# Clear any mainnet session files so bridge re-auths cleanly
rm -f /opt/bilshenz/binance_trading_system/python/.binance_session.json \
      /var/lib/bilshenz/*.session 2>/dev/null || true
systemctl restart bilshenz-binance-api
sleep 8
systemctl is-active bilshenz-binance-api
curl -sS --max-time 12 http://127.0.0.1:8766/health > /tmp/h.json
python3 - <<'PY'
import json
d=json.load(open('/tmp/h.json'))
s=d.get('scanner') or {{}}
print('mode', d.get('mode'), 'connected', d.get('connected'), 'exec', s.get('can_execute'), 'block', s.get('exec_block'))
print('strategy', s.get('strategy_id') or s.get('strategy_name'))
PY
# ping testnet from droplet
curl -sS -o /dev/null -w 'testnet_ping=%{{http_code}}\n' --max-time 12 https://testnet.binancefuture.com/fapi/v1/ping || true
"""
    _, o, e = c.exec_command(cmd, timeout=120)
    print(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        print("STDERR:", err[-1500:])
    code = o.channel.recv_exit_status()
    c.close()

    # public check
    try:
        with urllib.request.urlopen(f"http://{HOST}:8766/health", timeout=12) as r:
            d = json.loads(r.read().decode())
        print(
            "PUBLIC",
            "mode=",
            d.get("mode"),
            "connected=",
            d.get("connected"),
            "exec=",
            (d.get("scanner") or {}).get("can_execute"),
        )
    except Exception as ex:
        print("PUBLIC_FAIL", ex)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
