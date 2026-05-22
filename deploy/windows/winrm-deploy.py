#!/usr/bin/env python3
"""Deploy via WinRM when SSH blocked. Set VPS_PW, VPS_USER, VPS_HOST."""
import os
import sys
import tempfile
import zipfile
from pathlib import Path

import winrm

HOST = os.environ.get("VPS_HOST", "104.194.140.203")
USER = os.environ.get("VPS_USER", "Administrator")
PW = os.environ.get("VPS_PW", "")
ROOT = Path(__file__).resolve().parent.parent.parent


def make_bundle(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel in ["deploy/windows", "backend", "mt5_trading_system/python"]:
            src = ROOT / rel.replace("/", os.sep)
            if not src.exists():
                continue
            for f in src.rglob("*"):
                if f.is_file() and ".venv" not in str(f) and "node_modules" not in str(f):
                    zf.write(f, str(f.relative_to(ROOT)).replace("\\", "/"))


def main() -> int:
    if not PW:
        print("Set VPS_PW", file=sys.stderr)
        return 2
    bundle = Path(tempfile.gettempdir()) / "bilshenz-vps-bundle.zip"
    make_bundle(bundle)
    print(f"Bundle {bundle.stat().st_size // 1024} KB")

    s = winrm.Session(
        f"http://{HOST}:5985/wsman",
        auth=(USER, PW),
        transport="ntlm",
        server_cert_validation="ignore",
        operation_timeout_sec=300,
        read_timeout_sec=310,
    )
    r = s.run_cmd("hostname")
    print("WinRM OK:", r.std_out.decode().strip())

    # Upload zip via base64 chunks (winrm file limit)
    import base64
    data = bundle.read_bytes()
    b64 = base64.b64encode(data).decode("ascii")
    chunk = 6000
    ps = [
        "powershell -NoProfile -Command \"",
        "New-Item -ItemType Directory -Force -Path C:/opt | Out-Null;",
        "if (Test-Path C:/opt/b64.txt) { Remove-Item C:/opt/b64.txt };",
        "\"",
    ]
    s.run_ps("".join(ps))
    for i in range(0, len(b64), chunk):
        part = b64[i : i + chunk]
        s.run_ps(f"Add-Content -Path C:/opt/b64.txt -Value '{part}' -NoNewline")
    s.run_ps(
        "powershell -NoProfile -Command \""
        "[IO.File]::WriteAllBytes('C:/opt/bilshenz-bundle.zip', "
        "[Convert]::FromBase64String([IO.File]::ReadAllText('C:/opt/b64.txt'))); "
        "Remove-Item C:/opt/b64.txt; "
        "Expand-Archive -Force C:/opt/bilshenz-bundle.zip C:/opt/bilshenz; "
        "powershell -ExecutionPolicy Bypass -File C:/opt/bilshenz/deploy/windows/vps-full-install.ps1"
        "\""
    )
    print("Deploy command sent. Check C:/opt/vps-install.log on VPS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
