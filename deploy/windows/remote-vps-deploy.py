#!/usr/bin/env python3
"""Upload repo deploy bundle to Windows VPS and run vps-full-install.ps1."""
from __future__ import annotations

import os
import sys
import tempfile
import zipfile
from pathlib import Path

import paramiko

HOST = os.environ.get("VPS_HOST", "104.194.140.203")
USER = os.environ.get("VPS_USER", "Administrator")
PW = os.environ.get("VPS_PW", "")
ROOT = Path(__file__).resolve().parent.parent.parent


def make_bundle(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in ["deploy/windows", "backend", "mt5_trading_system/python", "mt5_trading_system/python/requirements.txt"]:
            src = ROOT / rel.replace("/", os.sep)
            if not src.exists():
                continue
            if src.is_file():
                zf.write(src, rel.replace("\\", "/"))
            else:
                for f in src.rglob("*"):
                    if f.is_file() and ".venv" not in str(f) and "node_modules" not in str(f):
                        arc = str(f.relative_to(ROOT)).replace("\\", "/")
                        zf.write(f, arc)


def main() -> int:
    if not PW:
        print("Set VPS_PW", file=sys.stderr)
        return 2
    bundle = Path(tempfile.gettempdir()) / "bilshenz-vps-bundle.zip"
    make_bundle(bundle)
    print(f"Bundle {bundle.stat().st_size // 1024} KB")

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    for port in (22, 2222):
        try:
            client.connect(
                HOST, port=port, username=USER, password=PW,
                timeout=30, banner_timeout=30, auth_timeout=30,
            )
            print(f"SSH connected on port {port}")
            break
        except Exception:
            continue
    else:
        print(f"SSH failed to {HOST}. Open port 22 in cloud firewall + run enable-remote-admin.ps1 on VPS")
        print(f"Fallback bundle: {bundle}")
        return 1

    sftp = client.open_sftp()
    remote_zip = "C:/opt/bilshenz-bundle.zip"
    remote_ps1 = "C:/opt/vps-full-install.ps1"
    for d in ("C:/opt", "/opt"):
        try:
            sftp.mkdir(d)
        except OSError:
            pass
    sftp.put(str(bundle), remote_zip)
    sftp.put(str(ROOT / "deploy/windows/vps-full-install.ps1"), remote_ps1)
    sftp.close()

    cmd = (
        "powershell -NoProfile -ExecutionPolicy Bypass -Command \""
        "New-Item -ItemType Directory -Force -Path C:/opt | Out-Null; "
        "Expand-Archive -Force C:/opt/bilshenz-bundle.zip C:/opt/bilshenz-src; "
        "if (Test-Path C:/opt/bilshenz) { Remove-Item C:/opt/bilshenz -Recurse -Force }; "
        "if (Test-Path C:/opt/bilshenz-src) { Move-Item C:/opt/bilshenz-src C:/opt/bilshenz }; "
        "powershell -ExecutionPolicy Bypass -File C:/opt/vps-full-install.ps1"
        "\""
    )
    print("Running install on VPS (10-20 min)...")
    stdin, stdout, stderr = client.exec_command(cmd, timeout=1200)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
    if err:
        sys.stderr.buffer.write(err.encode("utf-8", errors="replace"))
    client.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
