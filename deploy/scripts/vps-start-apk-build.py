#!/usr/bin/env python3
"""Kick off VPS APK build in background (nohup) so SSH Unicode cannot kill it."""
import os
import sys
import time

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")


def sh(client, cmd, timeout=120):
    _, stdout, stderr = client.exec_command(cmd, get_pty=True, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)

    boot = (
        "cd /opt/bilshenz && git fetch origin && git reset --hard origin/main && "
        "chmod +x deploy/ubuntu/build-apk-on-vps.sh && "
        "pkill -f build-apk-on-vps.sh 2>/dev/null || true; "
        "pkill -f gradlew 2>/dev/null || true; "
        "nohup bash deploy/ubuntu/build-apk-on-vps.sh >/var/log/bilshenz/apk-build.out 2>&1 & "
        "echo STARTED_PID=$!; sleep 2; "
        "pgrep -af build-apk-on-vps || echo NOT_RUNNING; "
        "tail -n 20 /var/log/bilshenz/apk-build.log 2>/dev/null || true"
    )
    code, out, err = sh(client, boot, timeout=180)
    print(out)
    if err.strip():
        print(err, file=sys.stderr)
    client.close()
    return 0 if "STARTED_PID=" in out else code


if __name__ == "__main__":
    raise SystemExit(main())
