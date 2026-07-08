#!/usr/bin/env python3
"""Ensure production auth secrets exist, restart desk-api, start APK build."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")


def run(client, cmd, timeout=300):
    print(f"$ {cmd[:180]}")
    _, stdout, stderr = client.exec_command(cmd, get_pty=True, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
    if err.strip():
        sys.stderr.buffer.write(err.encode("utf-8", errors="replace"))
    print(f"[exit={code}]")
    return code, out


FIX_ENV = r'''
set -e
ENV=/etc/bilshenz.env
touch "$ENV"
chmod 600 "$ENV"
grep -q '^PRODUCTION_MODE=' "$ENV" || echo 'PRODUCTION_MODE=1' >> "$ENV"
grep -q '^STRATEGY_FREEZE=' "$ENV" || echo 'STRATEGY_FREEZE=1' >> "$ENV"
if ! grep -q '^AUTH_JWT_SECRET=' "$ENV"; then
  SECRET=$(openssl rand -hex 32)
  echo "AUTH_JWT_SECRET=$SECRET" >> "$ENV"
  echo "ADDED_AUTH_JWT_SECRET"
else
  LEN=$(grep '^AUTH_JWT_SECRET=' "$ENV" | cut -d= -f2- | tr -d '\r\n' | wc -c)
  if [ "$LEN" -lt 32 ]; then
    SECRET=$(openssl rand -hex 32)
    sed -i "s/^AUTH_JWT_SECRET=.*/AUTH_JWT_SECRET=$SECRET/" "$ENV"
    echo "ROTATED_SHORT_AUTH_JWT_SECRET"
  else
    echo "AUTH_JWT_SECRET_OK"
  fi
fi
systemctl restart bilshenz-desk-api
sleep 2
curl -s --max-time 8 http://127.0.0.1:8791/health
echo
systemctl is-active bilshenz-desk-api
'''


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)

    run(client, "bash -lc " + repr(FIX_ENV), timeout=120)
    run(client, "cd /opt/bilshenz && git fetch origin && git reset --hard origin/main && git log -1 --oneline", timeout=180)
    run(client, "chmod +x /opt/bilshenz/deploy/ubuntu/build-apk-on-vps.sh /opt/bilshenz/deploy/scripts/*.py 2>/dev/null; true")
    run(client, "pkill -f build-apk-on-vps.sh || true; pkill -f 'gradlew assembleRelease' || true")
    run(
        client,
        "nohup bash /opt/bilshenz/deploy/ubuntu/build-apk-on-vps.sh > /var/log/bilshenz/apk-build.out 2>&1 < /dev/null & echo START_OK; sleep 4; pgrep -af build-apk-on-vps || pgrep -af 'sdkmanager|gradlew|expo' || echo NOT_RUNNING; tail -n 25 /var/log/bilshenz/apk-build.log 2>/dev/null || true",
        timeout=60,
    )

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
