#!/usr/bin/env python3
"""Probe new DO droplet and report Bilshenz install state."""
from __future__ import annotations

import os
import socket
import sys

HOST = os.environ.get("VPS_HOST", "161.35.112.53")
PASSWORD = os.environ.get("VPS_PASSWORD", "")


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    s = socket.socket()
    s.settimeout(15)
    try:
        s.connect((HOST, 22))
        print("tcp22 open")
        s.close()
    except Exception as e:
        print("tcp22 closed:", e)
        return 1

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(
        HOST,
        username="root",
        password=PASSWORD,
        timeout=45,
        look_for_keys=False,
        allow_agent=False,
        banner_timeout=45,
    )
    cmd = r"""
hostname
ls -la /opt/bilshenz 2>/dev/null | head -8 || echo NO_OPT_BILSHENZ
test -f /etc/bilshenz.env && echo HAS_ENV || echo NO_ENV
systemctl list-units --type=service --all 'bilshenz*' 2>/dev/null | head -20 || true
df -h / | tail -1
command -v docker; command -v node; command -v npm; command -v python3; command -v git
ufw status || true
"""
    _, o, e = c.exec_command(cmd, timeout=60)
    print(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        print("STDERR:", err[-1500:])
    c.close()
    print("SSH_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
