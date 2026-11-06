#!/usr/bin/env python3
"""Build the Oracle bundle from the working tree, including uncommitted fixes.

Allow-list only: the repo root also holds credentials and audit output, so a file ships only
if git tracks it under an allowed path or it is named in EXTRA.

  python deploy/oracle/make_bundle.py
"""
from __future__ import annotations

import io
import re
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "deploy" / "oracle" / "dist"
ALLOWED = (
    "backend/",
    "binance_trading_system/python/",
    "deploy/systemd/bilshenz-binance-api.service",
    "deploy/systemd/bilshenz-desk-api.service",
    "deploy/ubuntu/healthcheck.sh",
    # Read by test_permanent_leak_locks.py on the server.
    "frontend/broker/binanceFuturesApi.js",
    "frontend/components/OpenPositionsPanel.js",
    "frontend/lib/liveFloatingPnl.js",
    "frontend/lib/liveFloatingPnl.test.js",
)
EXTRA = (
    "binance_trading_system/python/test_audit_nov_fixes.py",
    "deploy/oracle/install-oracle.sh",
    "deploy/oracle/preflight.sh",
    "deploy/oracle/arm-trading.sh",
    "deploy/oracle/bilshenz.env.template",
)
BLOCKED_NAME = re.compile(r"(^|/)(\.env[^/]*|_auth[^/]*|.*\.pem|.*\.key|id_(rsa|ed25519)[^/]*)$", re.I)
# A value after these names means a real secret reached the bundle.
SECRET_VALUE = re.compile(
    rb"(?m)^\s*(BINANCE_API_KEY|BINANCE_API_SECRET|BRIDGE_TOKEN|DESK_API_KEY|AUTH_JWT_SECRET|SESSION_ENC_KEY)=\S+"
)
TEXT_LF = (".sh", ".service", ".template")


def main() -> int:
    tracked = subprocess.check_output(["git", "ls-files", "-c"], cwd=ROOT, text=True).splitlines()
    files = [f for f in tracked if f.startswith(ALLOWED)] + list(EXTRA)
    sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    OUT.mkdir(exist_ok=True)
    target = OUT / f"bilshenz-oracle-{sha}-dirty.tar.gz"
    count = 0
    refused = ""
    with tarfile.open(target, "w:gz") as tar:
        for rel in sorted(set(files)):
            path = ROOT / rel
            if not path.is_file():
                continue
            if BLOCKED_NAME.search(rel):
                print("skipped", rel)
                continue
            data = path.read_bytes()
            if SECRET_VALUE.search(data):
                refused = rel
                break
            if rel.endswith(TEXT_LF):
                data = data.replace(b"\r\n", b"\n")
            info = tarfile.TarInfo(rel)
            info.size = len(data)
            info.mode = 0o755 if rel.endswith(".sh") else 0o644
            tar.addfile(info, io.BytesIO(data))
            count += 1
    if refused:
        target.unlink()
        print("REFUSED secret value in", refused, "- no bundle written")
        return 1
    print(f"{target}  files={count}  bytes={target.stat().st_size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
