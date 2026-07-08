#!/usr/bin/env python3
"""Restart APK build after compileSdk fix."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r'''
export GIT_PAGER=cat
export PAGER=cat
set +e
cd /opt/bilshenz
git fetch origin
git reset --hard origin/main
GIT_PAGER=cat git --no-pager log -1 --oneline
chmod +x deploy/ubuntu/build-apk-on-vps.sh
pkill -f build-apk-on-vps.sh 2>/dev/null || true
pkill -f GradleWrapperMain 2>/dev/null || true
pkill -f 'gradlew assembleRelease' 2>/dev/null || true
sleep 2
: > /var/log/bilshenz/apk-build.out
nohup bash /opt/bilshenz/deploy/ubuntu/build-apk-on-vps.sh > /var/log/bilshenz/apk-build.out 2>&1 < /dev/null &
disown || true
echo START_OK
sleep 8
pgrep -af 'build-apk-on-vps|GradleWrapperMain|expo|sdkmanager|npm' | head -n 20 || echo NOT_RUNNING
echo '--- out ---'
tail -n 25 /var/log/bilshenz/apk-build.out | tr -cd '\11\12\15\40-\176'
'''


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    # Do not use get_pty — pagers and progress bars hang the channel.
    _, stdout, stderr = client.exec_command(CMD, timeout=180)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    sys.stdout.write(out)
    if err.strip():
        sys.stderr.write(err)
    client.close()
    return 0 if "START_OK" in out else 1


if __name__ == "__main__":
    raise SystemExit(main())
