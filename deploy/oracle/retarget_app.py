#!/usr/bin/env python3
"""Point the phone app at the new server. The IP is baked into the build, so rebuild afterwards.

  python deploy/oracle/retarget_app.py NEW_IP            # preview
  python deploy/oracle/retarget_app.py NEW_IP --apply
"""
from __future__ import annotations

import ipaddress
import sys
from pathlib import Path

OLD_IP = "159.223.29.223"
ROOT = Path(__file__).resolve().parents[2]
FILES = (
    "frontend/app.json",
    "frontend/eas.json",
    "frontend/components/OnboardingGate.js",
    "frontend/.env",
    "frontend/.env.local",
)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    new_ip = str(ipaddress.IPv4Address(sys.argv[1]))
    apply = "--apply" in sys.argv[2:]
    for rel in FILES:
        path = ROOT / rel
        if not path.is_file():
            continue
        data = path.read_bytes()
        n = data.count(OLD_IP.encode())
        print(f"{rel}: {n} replacement(s)")
        if apply and n:
            path.write_bytes(data.replace(OLD_IP.encode(), new_ip.encode()))
    print("Applied. Rebuild the APK." if apply else "Preview only. Add --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
