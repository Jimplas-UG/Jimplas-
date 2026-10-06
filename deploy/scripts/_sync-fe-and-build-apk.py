#!/usr/bin/env python3
"""Sync current frontend (ghost-floating + desk UI) to FRA and start release APK build.

Does NOT clear BRIDGE_TOKEN — new APK bakes EXPO_PUBLIC_* from /etc/bilshenz.env.
"""
from __future__ import annotations

from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

FE_FILES = [
    "frontend/lib/liveFloatingPnl.js",
    "frontend/lib/liveFloatingPnl.test.js",
    "frontend/lib/envConfig.js",
    "frontend/lib/wsReconnect.js",
    "frontend/hooks/useBinanceLiveFeed.js",
    "frontend/hooks/useTickScanner.js",
    "frontend/screens/TradeScreen.js",
    "frontend/screens/ScannerScreen.js",
    "frontend/App.js",
    "frontend/app.config.js",
    "frontend/app.json",
    "frontend/package.json",
    "frontend/components/OpenPositionsPanel.js",
    "frontend/components/BinanceBridgePanel.js",
    "frontend/components/OnboardingGate.js",
    "frontend/broker/binanceFuturesApi.js",
    "frontend/broker/binanceTickStream.js",
    "frontend/broker/binanceScannerApi.js",
    "deploy/ubuntu/build-apk-fra.sh",
]

STARTER = r"""#!/bin/bash
set +e
kill $(cat /var/run/bilshenz-apk-build.pid 2>/dev/null) 2>/dev/null
pkill -f 'gradlew assembleRelease' 2>/dev/null
pkill -f 'expo prebuild' 2>/dev/null
rm -f /var/log/bilshenz/apk-build.log /var/log/bilshenz/apk-build-nohup.out
chmod +x /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh
# Keep BRIDGE_TOKEN — bake into APK from /etc/bilshenz.env
grep -E '^(BRIDGE_TOKEN|EXPO_PUBLIC_|DESK_API)' /etc/bilshenz.env | sed 's/=.*/=***/' || true
cd /opt/bilshenz/frontend && node lib/liveFloatingPnl.test.js
grep -q heroFloatingPnl screens/TradeScreen.js
grep -q CLOSE_TOMBSTONE_MS hooks/useBinanceLiveFeed.js
nohup bash /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh >/var/log/bilshenz/apk-build-nohup.out 2>&1 &
echo $! > /var/run/bilshenz-apk-build.pid
echo STARTED:$(cat /var/run/bilshenz-apk-build.pid)
sleep 6
ps -p $(cat /var/run/bilshenz-apk-build.pid) -o pid,etime,cmd || true
tail -n 25 /var/log/bilshenz/apk-build-nohup.out 2>/dev/null || true
tail -n 15 /var/log/bilshenz/apk-build.log 2>/dev/null || true
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in FE_FILES:
        local = ROOT / rel
        if not local.exists():
            print("SKIP missing", rel)
            continue
        remote = f"/opt/bilshenz/{rel}"
        # ensure parent exists
        parent = str(Path(remote).parent).replace("\\", "/")
        try:
            sftp.stat(parent)
        except OSError:
            c.exec_command(f"mkdir -p {parent}", timeout=15)
        sftp.put(str(local), remote)
        print("uploaded", rel)
    with sftp.file("/tmp/start-bilshenz-apk.sh", "w") as f:
        f.write(STARTER)
    sftp.close()
    _, o, e = c.exec_command("chmod +x /tmp/start-bilshenz-apk.sh && bash /tmp/start-bilshenz-apk.sh", timeout=90)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err.encode("ascii", "replace").decode("ascii")[-1500:])
    c.close()


if __name__ == "__main__":
    main()
