#!/usr/bin/env python3
"""Why EMERGENCY_STOP now — health, risk file, 1000RATS timeline."""
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
from pathlib import Path

tok = open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
H = {'Authorization': 'Bearer ' + tok}

def get(url):
    req = urllib.request.Request(url, headers=H)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

h = json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc = h.get('scanner') or {}
print('=== NOW ===')
print('can_execute', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'), 'block', sc.get('exec_block'))
print('rule_kernel', sc.get('rule_kernel'))
print('active', sc.get('active_symbol'), 'last_exec_error', sc.get('last_exec_error'))
pos = get('http://127.0.0.1:8766/api/positions')
for p in (pos.get('positions') or []):
    print('POS', p.get('symbol'), p.get('positionSide'), 'vol', p.get('volume'), 'lev', p.get('leverage'), p.get('exchange_leverage'), 'policy', p.get('policy_leverage'))

risk = Path('/var/lib/bilshenz/scanner-risk.json')
if risk.exists():
    print('RISK_FILE', risk.read_text()[:500])
PY

echo '=== LOG 1000RATS + HALT (last 80) ==='
grep -E '1000RATSUSDT|PARTIAL_CLOSE|RULE_KERNEL_EMERGENCY|set_exec_enabled\(False\)|scanner/exec|MANUAL.*1000RATS|leverage 1000RATS' /var/log/bilshenz/app.log | tail -n 80
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
        sys.stderr.write(err[-2000:])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
