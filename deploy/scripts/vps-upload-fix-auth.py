#!/usr/bin/env python3
"""Upload and run fix-auth-env.sh, then report APK build status."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
LOCAL_FIX = os.path.join(ROOT, "deploy", "ubuntu", "fix-auth-env.sh")
REMOTE_FIX = "/opt/bilshenz/deploy/ubuntu/fix-auth-env.sh"


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)

    sftp = client.open_sftp()
    sftp.put(LOCAL_FIX, REMOTE_FIX)
    sftp.close()

    cmds = [
        "chmod +x /opt/bilshenz/deploy/ubuntu/fix-auth-env.sh && bash /opt/bilshenz/deploy/ubuntu/fix-auth-env.sh",
        "pgrep -af 'build-apk-on-vps|gradlew|expo prebuild|sdkmanager' || echo NO_BUILD_PROC",
        "tail -n 40 /var/log/bilshenz/apk-build.log 2>/dev/null | tr -cd '\\11\\12\\15\\40-\\176' | tail -n 40",
        "ls -lh /opt/bilshenz/frontend/dist/ 2>/dev/null || echo NO_DIST",
        "curl -s --max-time 8 http://127.0.0.1:8791/download; echo",
        "curl -s --max-time 8 -X POST http://127.0.0.1:8791/v1/auth/login -H 'Content-Type: application/json' -d '{\"email\":\"test@example.com\",\"password\":\"badpass\"}'; echo",
    ]
    for cmd in cmds:
        print(f"$ {cmd[:100]}")
        _, stdout, stderr = client.exec_command(cmd, get_pty=True, timeout=180)
        out = stdout.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
        print(f"[exit={code}]")

    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
