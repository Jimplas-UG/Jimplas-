#!/usr/bin/env python3
"""Upload deploy bundle and run production-setup.sh on Ubuntu VPS."""
from __future__ import annotations

import os
import pathlib
import sys

import paramiko

HOST = os.environ.get("VPS_HOST", "209.97.177.33")
USER = os.environ.get("VPS_USER", "root")
PW = os.environ.get("VPS_PW", "")
ROOT = pathlib.Path(__file__).resolve().parent.parent
REMOTE = "/tmp/bilshenz-deploy"


def upload_tree(sftp: paramiko.SFTPClient, local: pathlib.Path, remote: str) -> None:
    try:
        sftp.mkdir(remote)
    except OSError:
        pass
    for p in local.iterdir():
        r = f"{remote}/{p.name}"
        if p.is_dir():
            upload_tree(sftp, p, r)
        else:
            sftp.put(str(p), r)


def main() -> int:
    if not PW:
        print("Set VPS_PW environment variable", file=sys.stderr)
        return 2
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {HOST}...")
    client.connect(HOST, username=USER, password=PW, timeout=25, banner_timeout=25, auth_timeout=25)
    sftp = client.open_sftp()
    try:
        client.exec_command(f"rm -rf {REMOTE} && mkdir -p {REMOTE}/systemd {REMOTE}/logrotate {REMOTE}/production")
    except Exception:
        pass
    deploy = ROOT / "deploy"
    for name in [
        "production-setup.sh",
        "requirements.txt",
        "tradingbot.env.example",
        "watchdog.ts",
        "screen-fallback.sh",
    ]:
        local = deploy / name
        if local.exists():
            sftp.put(str(local), f"{REMOTE}/{name}")
    logrotate = deploy / "logrotate" / "tradingbot"
    if logrotate.exists():
        sftp.put(str(logrotate), f"{REMOTE}/logrotate-tradingbot")
    for svc in (deploy / "systemd").glob("*.service"):
        sftp.put(str(svc), f"{REMOTE}/systemd/{svc.name}")
    prod = ROOT / "backend" / "production"
    if prod.is_dir():
        upload_tree(sftp, prod, f"{REMOTE}/production")
    sftp.close()
    client.exec_command(f"sed -i 's/\\r$//' {REMOTE}/*.sh 2>/dev/null; true", timeout=30)
    cmd = f"chmod +x {REMOTE}/production-setup.sh && DEPLOY_SRC={REMOTE} bash {REMOTE}/production-setup.sh"
    print("Running production-setup.sh (may take several minutes)...")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=900)
    out = stdout.read().decode()
    err = stderr.read().decode()
    code = stdout.channel.recv_exit_status()
    sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
    sys.stdout.buffer.write(b"\n")
    if err:
        sys.stderr.buffer.write(err.encode("utf-8", errors="replace"))
        sys.stderr.buffer.write(b"\n")
    if code == 0:
        _, so, _ = client.exec_command(
            "systemctl is-active bilshenz-desk-api bilshenz-forward-bot bilshenz-watchdog 2>/dev/null; "
            "curl -sf http://127.0.0.1:8791/health || echo desk-health-fail",
            timeout=30,
        )
        print(so.read().decode())
    client.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
