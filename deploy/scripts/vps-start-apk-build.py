#!/usr/bin/env python3
"""Start FRA APK build and optionally open bridge for tokenless old APKs."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import paramiko

HOST = os.environ.get("VPS_HOST", "159.223.29.223")
KEY = Path.home() / ".ssh" / "id_ed25519"
OPEN_BRIDGE = os.environ.get("OPEN_BRIDGE", "1") == "1"
ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)

    # upload build script + onboarding fix
    sftp = c.open_sftp()
    sftp.put(str(ROOT / "deploy/ubuntu/build-apk-fra.sh"), "/opt/bilshenz/deploy/ubuntu/build-apk-fra.sh")
    sftp.put(
        str(ROOT / "frontend/components/OnboardingGate.js"),
        "/opt/bilshenz/frontend/components/OnboardingGate.js",
    )
    sftp.close()

    open_cmd = ""
    if OPEN_BRIDGE:
        open_cmd = r"""
python3 - <<'PY'
from pathlib import Path
p=Path('/etc/bilshenz.env')
lines=[]
for line in p.read_text().splitlines():
    if line.startswith('BRIDGE_TOKEN='):
        lines.append('BRIDGE_TOKEN=')
    else:
        lines.append(line)
p.write_text('\n'.join(lines)+'\n')
print('bridge_token_cleared_for_old_apk')
PY
systemctl restart bilshenz-binance-api
sleep 5
"""

    cmd = open_cmd + r"""
chmod +x /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh
mkdir -p /var/log/bilshenz
pkill -f build-apk-fra.sh || true
nohup bash /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh > /var/log/bilshenz/apk-build-nohup.out 2>&1 &
echo BUILD_STARTED
sleep 3
ps aux | grep build-apk-fra | grep -v grep || true
tail -n 20 /var/log/bilshenz/apk-build.log 2>/dev/null || echo waiting_for_log
tail -n 20 /var/log/bilshenz/apk-build-nohup.out 2>/dev/null || true
curl -sS --max-time 8 http://127.0.0.1:8766/health | python3 -c "import sys,json;d=json.load(sys.stdin);print('connected',d.get('connected'),'exec',(d.get('scanner') or {}).get('can_execute'))"
"""
    _, o, e = c.exec_command(cmd, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err[-1500:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
