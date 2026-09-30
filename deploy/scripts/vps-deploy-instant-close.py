#!/usr/bin/env python3
"""Deploy instant close (no confirm + optimistic UI + clear cool) and rebuild APK."""
from __future__ import annotations

from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

FILES = [
    "binance_trading_system/python/binance_connector.py",
    "frontend/components/OpenPositionsPanel.js",
    "frontend/broker/binanceFuturesApi.js",
    "frontend/hooks/useBinanceLiveFeed.js",
]

CMD = r"""
set -euo pipefail
systemctl restart bilshenz-binance-api
sleep 6
systemctl is-active bilshenz-binance-api
cat >/tmp/start-bilshenz-apk.sh <<'BASH'
#!/bin/bash
set +e
kill $(cat /var/run/bilshenz-apk-build.pid 2>/dev/null) 2>/dev/null
pkill -f 'gradlew assembleRelease' 2>/dev/null
pkill -f 'expo prebuild' 2>/dev/null
rm -f /var/log/bilshenz/apk-build.log /var/log/bilshenz/apk-build-nohup.out
nohup bash /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh >/var/log/bilshenz/apk-build-nohup.out 2>&1 &
echo $! > /var/run/bilshenz-apk-build.pid
echo STARTED:$(cat /var/run/bilshenz-apk-build.pid)
BASH
chmod +x /tmp/start-bilshenz-apk.sh
bash /tmp/start-bilshenz-apk.sh
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in FILES:
        local = ROOT / rel.replace("/", "\\")
        remote = f"/opt/bilshenz/{rel}"
        print(f"upload {rel}")
        sftp.put(str(local), remote)
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=90)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR:", err[-1200:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
