#!/usr/bin/env python3
"""Force AUTH_JWT into systemd drop-in and extract Gradle failure."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

REMOTE = r"""
set -e
python3 - <<'PY'
from pathlib import Path
import secrets
p = Path('/etc/bilshenz.env')
text = p.read_text(encoding='utf-8', errors='replace').replace('\r\n', '\n').replace('\r', '\n')
keys = {}
for ln in text.split('\n'):
    ln = ln.strip()
    if not ln or ln.startswith('#') or '=' not in ln:
        continue
    k, v = ln.split('=', 1)
    keys[k.strip()] = v.strip().strip('"').strip("'")
if len(keys.get('AUTH_JWT_SECRET', '')) < 32:
    keys['AUTH_JWT_SECRET'] = secrets.token_hex(32)
keys['PRODUCTION_MODE'] = '1'
keys.setdefault('STRATEGY_FREEZE', '1')
p.write_text('\n'.join(f'{k}={v}' for k, v in keys.items()) + '\n', encoding='utf-8')
print('AUTH_LEN', len(keys['AUTH_JWT_SECRET']))
PY

AUTH=$(grep '^AUTH_JWT_SECRET=' /etc/bilshenz.env | cut -d= -f2-)
mkdir -p /etc/systemd/system/bilshenz-desk-api.service.d
cat > /etc/systemd/system/bilshenz-desk-api.service.d/override.conf <<EOF
[Service]
Environment=NODE_ENV=production
Environment=PRODUCTION_MODE=1
Environment=AUTH_JWT_SECRET=$AUTH
EOF
systemctl daemon-reload
systemctl restart bilshenz-desk-api
sleep 3
echo '== DESK LOG =='
tail -n 12 /var/log/bilshenz/desk-api.log | tr -cd '\11\12\15\40-\176'
echo
echo '== LOGIN =='
curl -s --max-time 8 -X POST http://127.0.0.1:8791/v1/auth/login -H 'Content-Type: application/json' --data-binary '{"email":"x@y.com","password":"bad"}'
echo
echo '== GRADLE =='
python3 - <<'PY'
from pathlib import Path
t = Path('/var/log/bilshenz/apk-build.log').read_text(errors='replace')
for marker in ('What went wrong', 'Execution failed', 'BUILD FAILED', 'OutOfMemory'):
    idx = t.rfind(marker)
    print('MARKER', marker, 'IDX', idx)
    if idx >= 0:
        print(t[idx:idx+1200])
        print('----')
PY
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, stdout, _ = client.exec_command(REMOTE, get_pty=True, timeout=180)
    out = stdout.read().decode("utf-8", errors="replace")
    sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
