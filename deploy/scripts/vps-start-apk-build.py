#!/usr/bin/env python3
"""Start VPS APK build via nohup and verify process is alive."""
import os
import sys
import time

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)

    steps = [
        "cd /opt/bilshenz && git fetch origin && git reset --hard origin/main && git log -1 --oneline",
        "chmod +x /opt/bilshenz/deploy/ubuntu/build-apk-on-vps.sh",
        "mkdir -p /var/log/bilshenz /opt/bilshenz/frontend/dist",
        "pkill -f '/opt/bilshenz/deploy/ubuntu/build-apk-on-vps.sh' || true",
        "pkill -f 'gradlew assembleRelease' || true",
        "nohup bash /opt/bilshenz/deploy/ubuntu/build-apk-on-vps.sh > /var/log/bilshenz/apk-build.out 2>&1 < /dev/null & echo START_OK",
        "sleep 3",
        "pgrep -af build-apk-on-vps || pgrep -af 'sdkmanager|gradlew|expo prebuild' || echo NOT_RUNNING",
        "tail -n 30 /var/log/bilshenz/apk-build.log 2>/dev/null || echo NO_LOG_YET",
        "tail -n 20 /var/log/bilshenz/apk-build.out 2>/dev/null || true",
    ]

    for cmd in steps:
        print(f"$ {cmd}")
        _, stdout, stderr = client.exec_command(cmd, get_pty=True, timeout=300)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
        if err.strip():
            sys.stderr.buffer.write(err.encode("utf-8", errors="replace"))
        print(f"[exit={code}]")
        if cmd.startswith("nohup") and "START_OK" not in out:
            client.close()
            return 1

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
