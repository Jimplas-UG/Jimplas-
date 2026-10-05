#!/usr/bin/env python3
"""Restore FRA tokens + sync fixed frontend bridge files + ensure APK route."""
from __future__ import annotations

import os
from pathlib import Path

import paramiko

HOST = os.environ.get("VPS_HOST", "159.223.29.223")
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
BRIDGE_TOKEN = "c891511f887e44b19be9d92108eb1cb0fcce82e6b1cfc858"
DESK_KEY = "f44a0e6b7ea7b76418e484d6041e52da"

UPLOADS = [
    ("frontend/utils/binanceApiUrl.js", "/opt/bilshenz/frontend/utils/binanceApiUrl.js"),
    ("frontend/lib/binanceSession.js", "/opt/bilshenz/frontend/lib/binanceSession.js"),
    ("frontend/contexts/BinanceBridgeContext.js", "/opt/bilshenz/frontend/contexts/BinanceBridgeContext.js"),
    ("frontend/broker/binanceFuturesApi.js", "/opt/bilshenz/frontend/broker/binanceFuturesApi.js"),
    ("frontend/components/BinanceBridgePanel.js", "/opt/bilshenz/frontend/components/BinanceBridgePanel.js"),
    ("frontend/lib/envConfig.js", "/opt/bilshenz/frontend/lib/envConfig.js"),
    ("frontend/app.json", "/opt/bilshenz/frontend/app.json"),
    ("frontend/app.config.js", "/opt/bilshenz/frontend/app.config.js"),
    ("frontend/eas.json", "/opt/bilshenz/frontend/eas.json"),
]


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel, remote in UPLOADS:
        local = ROOT / rel.replace("/", os.sep)
        print(f"upload {rel}")
        sftp.put(str(local), remote)
    sftp.close()

    cmd = f"""
set -euo pipefail
ENVF=/etc/bilshenz.env
python3 - <<'PY'
from pathlib import Path
p = Path('/etc/bilshenz.env')
lines = p.read_text().splitlines()
kv = {{
  'BRIDGE_TOKEN': '{BRIDGE_TOKEN}',
  'DESK_API_KEY': '{DESK_KEY}',
  'BINANCE_TESTNET': '0',
  'BINANCE_PAPER': '0',
  'FORWARD_DRY_RUN': '0',
  'SCANNER_EXEC': '1',
}}
out = []
seen = set()
for line in lines:
    if '=' in line and not line.startswith('#'):
        k = line.split('=', 1)[0]
        if k in kv:
            out.append(f'{{k}}={{kv[k]}}')
            seen.add(k)
            continue
    out.append(line)
for k, v in kv.items():
    if k not in seen:
        out.append(f'{{k}}={{v}}')
p.write_text('\\n'.join(out) + '\\n')
p.chmod(0o600)
print('env_updated')
PY
systemctl restart bilshenz-binance-api bilshenz-desk-api
sleep 8
systemctl is-active bilshenz-binance-api bilshenz-desk-api
TOKEN=$(grep '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2-)
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json
python3 - <<'PY'
import json
d=json.load(open('/tmp/h.json'))
s=d.get('scanner') or {{}}
print('connected', d.get('connected'), 'mode', d.get('mode'), 'exec', s.get('can_execute'), 'block', s.get('exec_block'))
PY
curl -sS --max-time 10 -H "Authorization: Bearer {DESK_KEY}" http://127.0.0.1:8791/v1/binance/health | head -c 200
echo
# enable APK download route if helper exists
if [[ -f /opt/bilshenz/deploy/ubuntu/patch-desk-apk-route.mjs ]]; then
  node /opt/bilshenz/deploy/ubuntu/patch-desk-apk-route.mjs || true
  systemctl restart bilshenz-desk-api
  sleep 3
fi
echo SYNC_OK
"""
    _, o, e = c.exec_command(cmd, timeout=120)
    print(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        print("STDERR:", err[-2000:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
