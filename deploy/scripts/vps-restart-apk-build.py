#!/usr/bin/env python3
"""Restart APK build after compileSdk fix."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r'''
set -e
cd /opt/bilshenz
git fetch origin
git reset --hard origin/main
git log -1 --oneline
chmod +x deploy/ubuntu/build-apk-on-vps.sh
pkill -f build-apk-on-vps.sh || true
pkill -f GradleWrapperMain || true
pkill -f 'gradlew assembleRelease' || true
sleep 1
nohup bash /opt/bilshenz/deploy/ubuntu/build-apk-on-vps.sh > /var/log/bilshenz/apk-build.out 2>&1 < /dev/null &
echo START_OK
sleep 5
pgrep -af 'build-apk-on-vps|GradleWrapperMain|expo prebuild|sdkmanager' || echo NOT_RUNNING
tail -n 15 /var/log/bilshenz/apk-build.log | tr -cd '\11\12\15\40-\176' | tail -n 15
'''


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, stdout, _ = client.exec_command(CMD, get_pty=True, timeout=180)
    out = stdout.read().decode("utf-8", errors="replace")
    sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
    client.close()
    return 0 if "START_OK" in out else 1


if __name__ == "__main__":
    raise SystemExit(main())
