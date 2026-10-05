#!/usr/bin/env python3
"""Upload instant-tab frontend files to FRA and kick APK."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
FILES = [
    "frontend/App.js",
    "frontend/components/AppBottomNav.js",
]


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in FILES:
        data = (ROOT / rel).read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        with sftp.file(f"/opt/bilshenz/{rel}", "wb") as f:
            f.write(data)
        print("uploaded", rel)
    sftp.close()
    # Verify markers then kick apk
    _, o, e = c.exec_command(
        r"""
grep -q 'onPressIn' /opt/bilshenz/frontend/components/AppBottomNav.js && echo HAS_PRESS_IN
grep -q 'warm-mount' /opt/bilshenz/frontend/App.js && echo HAS_WARM_MOUNT
grep -q 'startTransition' /opt/bilshenz/frontend/App.js && echo STILL_HAS_TRANSITION || echo NO_TRANSITION
bash /tmp/start-bilshenz-apk.sh 2>/dev/null || true
""",
        timeout=30,
    )
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-800:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
