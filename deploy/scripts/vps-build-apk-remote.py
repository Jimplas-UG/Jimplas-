#!/usr/bin/env python3
"""Run long-running VPS APK build script via SSH."""
import os
import sys
import paramiko

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
SCRIPT = "/opt/bilshenz/deploy/ubuntu/build-apk-on-vps.sh"


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    cmd = f"cd /opt/bilshenz && git fetch origin && git reset --hard origin/main && chmod +x {SCRIPT} && bash {SCRIPT}"
    print(f"Running on {HOST} (15-30 min)...")
    stdin, stdout, stderr = client.exec_command(cmd, get_pty=True, timeout=3600)
    for line in iter(stdout.readline, ""):
        print(line, end="")
    err = stderr.read().decode("utf-8", errors="replace")
    if err:
        print(err, file=sys.stderr)
    code = stdout.channel.recv_exit_status()
    client.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
