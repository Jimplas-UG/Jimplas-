#!/usr/bin/env python3
"""One-shot VPS deploy via SSH password (paramiko)."""
import json
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

DEPLOY_CMD = r"""
set -e
cd /opt/bilshenz
git fetch origin
git checkout main
git reset --hard origin/main
git pull --ff-only origin main
bash deploy/ubuntu/serve-apk.sh
echo '---DOWNLOAD---'
curl -s http://127.0.0.1:8791/download
echo ''
echo '---HEALTH---'
curl -s http://127.0.0.1:8791/health
echo ''
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    try:
        import paramiko
    except ImportError:
        print("pip install paramiko", file=sys.stderr)
        return 1

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {USER}@{HOST}...")
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    stdin, stdout, stderr = client.exec_command(DEPLOY_CMD, get_pty=True, timeout=300)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    client.close()
    if out:
        print(out)
    if err:
        print(err, file=sys.stderr)
    if "unauthorized" in out and "---DOWNLOAD---" in out:
        dl = out.split("---DOWNLOAD---", 1)[-1].split("---HEALTH---")[0].strip()
        if "unauthorized" in dl:
            print("FAIL: /download still unauthorized", file=sys.stderr)
            return 1
    print(f"exit={code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
