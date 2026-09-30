#!/usr/bin/env python3
"""Deploy partition tap fix + faster tabs; keep partition $100; rebuild APK."""
from __future__ import annotations

from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

FILES = [
    "binance_trading_system/python/momentum_scanner.py",
    "frontend/components/InstitutionalRiskDesk.js",
    "frontend/broker/binanceScannerApi.js",
    "frontend/hooks/useDeskSession.js",
    "frontend/App.js",
    "frontend/screens/RiskScreen.js",
    "frontend/screens/TradeScreen.js",
]

CMD = r"""
set -euo pipefail
python3 <<'PY'
from pathlib import Path
import json
p = Path('/var/lib/bilshenz/scanner-risk.json')
raw = {
  'partition_usd': 100.0,
  'short_pct': 50.0,
  'long1_pct': 40.0,
  'long2_pct': 40.0,
  'locked': True,
  'exec_halted': False,
}
p.write_text(json.dumps(raw, indent=2) + '\n')
print('risk_file', raw)
PY
systemctl restart bilshenz-binance-api
sleep 8
TOKEN=$(python3 -c "from pathlib import Path; d={};
[d.__setitem__(a,b.strip().strip(chr(34)).strip(chr(39))) for a,b in (l.split('=',1) for l in Path('/etc/bilshenz.env').read_text().splitlines() if '=' in l and not l.startswith('#'))];
print(d.get('BRIDGE_TOKEN',''))")
# Prove re-subscribe $100 while locked works
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"partition_usd":100,"short_pct":50,"long1_pct":40,"long2_pct":40}' \
  http://127.0.0.1:8766/api/scanner/risk
echo
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" -H 'Content-Type: application/json' \
  -d '{"enabled":true}' http://127.0.0.1:8766/api/scanner/exec
echo
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json
python3 - <<'PY'
import json
h=json.load(open('/tmp/h.json'))
s=h.get('scanner') or {}
print('partition_usd', s.get('partition_usd'), 'locked', s.get('risk_locked'), 'exec', s.get('can_execute'), 'mode', h.get('mode'))
PY
# Kick APK
cat >/tmp/start-bilshenz-apk.sh <<'BASH'
#!/bin/bash
set +e
kill $(cat /var/run/bilshenz-apk-build.pid 2>/dev/null) 2>/dev/null
pkill -f 'gradlew assembleRelease' 2>/dev/null
pkill -f 'expo prebuild' 2>/dev/null
rm -f /var/log/bilshenz/apk-build.log /var/log/bilshenz/apk-build-nohup.out
nohup bash /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh >/var/log/bilshenz/apk-build-nohup.out 2>&1 &
echo $! > /var/run/bilshenz-apk-build.pid
echo STARTED:$(cat /var/run/bilshenz-apk-build.pid)
BASH
chmod +x /tmp/start-bilshenz-apk.sh
bash /tmp/start-bilshenz-apk.sh
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in FILES:
        local = ROOT / rel.replace("/", "\\")
        remote = f"/opt/bilshenz/{rel}"
        print(f"upload {rel}")
        sftp.put(str(local), remote)
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=120)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR:", err[-1500:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
