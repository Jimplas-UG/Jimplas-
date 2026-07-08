#!/usr/bin/env python3
"""Diagnose Gradle failure + force AUTH_JWT into systemd environment."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r'''
set -e
# Normalize bilshenz.env to LF and ensure AUTH_JWT is exported by systemd
python3 - <<'PY'
from pathlib import Path
p = Path('/etc/bilshenz.env')
text = p.read_text(encoding='utf-8', errors='replace').replace('\r\n','\n').replace('\r','\n')
lines = [ln for ln in text.split('\n') if ln.strip() and not ln.strip().startswith('#')]
keys = {}
for ln in lines:
    if '=' not in ln: continue
    k,v = ln.split('=',1)
    keys[k.strip()] = v.strip().strip('"').strip("'")
import secrets
if len(keys.get('AUTH_JWT_SECRET','')) < 32:
    keys['AUTH_JWT_SECRET'] = secrets.token_hex(32)
keys['PRODUCTION_MODE'] = keys.get('PRODUCTION_MODE') or '1'
keys['STRATEGY_FREEZE'] = keys.get('STRATEGY_FREEZE') or '1'
out = '\n'.join(f'{k}={v}' for k,v in keys.items()) + '\n'
p.write_text(out, encoding='utf-8')
print('ENV_KEYS', ','.join(sorted(keys)))
print('AUTH_LEN', len(keys.get('AUTH_JWT_SECRET','')))
PY
systemctl daemon-reload
systemctl restart bilshenz-desk-api
sleep 2
# Prove env is visible to the service
systemctl show bilshenz-desk-api -p Environment --no-pager | tr ' ' '\n' | grep -E 'AUTH_JWT|PRODUCTION_MODE|DESK_API' | sed 's/=.*/=***/' || true
grep AUTH_JWT /var/log/bilshenz/desk-api.log | tail -n 5 || true
curl -s --max-time 8 -X POST http://127.0.0.1:8791/v1/auth/login -H 'Content-Type: application/json' --data-binary '{"email":"x@y.com","password":"bad"}'; echo
echo '== GRADLE ERROR =='
grep -nE 'FAILED|error:|What went wrong|Execution failed|AAPT|OutOfMemory|BUILD FAILED' /var/log/bilshenz/apk-build.log | tail -n 40
echo '== GRADLE CONTEXT =='
grep -n 'What went wrong' -A 20 /var/log/bilshenz/apk-build.log | tail -n 40
'''


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, stdout, _ = client.exec_command(CMD, get_pty=True, timeout=120)
    out = stdout.read().decode("utf-8", errors="replace")
    sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
