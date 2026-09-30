#!/usr/bin/env python3
"""Force partition $50 via risk file reload + arm exec. No strategy rule changes."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set -euo pipefail
python3 <<'PY'
from pathlib import Path
import json
p = Path('/var/lib/bilshenz/scanner-risk.json')
p.parent.mkdir(parents=True, exist_ok=True)
raw = {
  'partition_usd': 50.0,
  'short_pct': 50.0,
  'long1_pct': 40.0,
  'long2_pct': 40.0,
  'locked': True,
  'exec_halted': False,
}
p.write_text(json.dumps(raw, indent=2) + '\n')
print('wrote', raw)
PY
systemctl restart bilshenz-binance-api
sleep 10
systemctl is-active bilshenz-binance-api
TOKEN=$(python3 -c "from pathlib import Path; d={};
[d.__setitem__(a,b.strip().strip(chr(34)).strip(chr(39))) for a,b in (l.split('=',1) for l in Path('/etc/bilshenz.env').read_text().splitlines() if '=' in l and not l.startswith('#'))];
print(d.get('BRIDGE_TOKEN',''))")
curl -sS --max-time 15 -H "X-Bridge-Token: $TOKEN" -H 'Content-Type: application/json' -d '{"enabled":true}' http://127.0.0.1:8766/api/scanner/exec
echo
curl -sS --max-time 15 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json
python3 <<'PY'
import json
h=json.load(open('/tmp/h.json'))
s=h.get('scanner') or {}
print('partition_usd', s.get('partition_usd'))
print('percents', s.get('short_partition_pct'), s.get('long1_partition_pct'), s.get('long2_partition_pct'))
print('risk_locked', s.get('risk_locked'))
print('can_execute', s.get('can_execute'), 'block', s.get('exec_block'))
print('exec_enabled', s.get('exec_enabled'), 'halted', s.get('user_exec_halted'))
print('strategy', s.get('strategy_id'), 'mode', h.get('mode'), 'connected', h.get('connected'))
print('risk_file', open('/var/lib/bilshenz/scanner-risk.json').read().strip())
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
