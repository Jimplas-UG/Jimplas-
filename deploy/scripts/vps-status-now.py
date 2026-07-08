#!/usr/bin/env python3
"""One-shot VPS status: auth secret, desk logs, APK build."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
set -e
echo '== ENV AUTH =='
grep -E '^(AUTH_JWT_SECRET|PRODUCTION_MODE|DESK_API_KEY)=' /etc/bilshenz.env | sed -E 's/(AUTH_JWT_SECRET|DESK_API_KEY)=.*/\1=***/'
echo '== SYSTEMD =='
systemctl show bilshenz-desk-api -p EnvironmentFiles -p ActiveState --no-pager
echo '== LOGIN LOCAL =='
curl -s --max-time 8 -X POST http://127.0.0.1:8791/v1/auth/login -H 'Content-Type: application/json' --data-binary '{"email":"test@example.com","password":"badpass"}'
echo
echo '== DOWNLOAD =='
curl -s --max-time 5 http://127.0.0.1:8791/download; echo
echo '== APK =='
ls -lh /opt/bilshenz/frontend/dist/ 2>/dev/null || echo NO_DIST
echo '== BUILD PROC =='
pgrep -af 'build-apk-on-vps|GradleWrapperMain|assembleRelease' || echo NO_BUILD
echo '== LOG TAIL =='
tail -n 30 /var/log/bilshenz/apk-build.log 2>/dev/null | tr -cd '\11\12\15\40-\176' | tail -n 30
echo '== DESK LOG AUTH =='
tail -n 40 /var/log/bilshenz/desk-api.log 2>/dev/null | tr -cd '\11\12\15\40-\176' | tail -n 40
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, stdout, _ = client.exec_command(CMD, get_pty=True, timeout=90)
    out = stdout.read().decode("utf-8", errors="replace")
    sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
