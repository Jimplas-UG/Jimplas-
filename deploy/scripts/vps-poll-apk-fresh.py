#!/usr/bin/env python3
"""Poll until a NEW APK build finishes (mtime after START_EPOCH)."""
import os
import sys
import time

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
MAX_MIN = int(os.environ.get("POLL_MINUTES", "45"))
START_EPOCH = int(os.environ.get("START_EPOCH", str(int(time.time()) - 60)))


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)

    for i in range(MAX_MIN):
        cmd = f"""
echo START_EPOCH={START_EPOCH}
if [[ -f /var/run/bilshenz-apk-build.pid ]]; then
  pid=$(cat /var/run/bilshenz-apk-build.pid)
  if kill -0 "$pid" 2>/dev/null; then echo BUILD_PID_ALIVE=$pid; else echo BUILD_PID_DEAD=$pid; fi
else
  echo NO_PID_FILE
fi
APK=/opt/bilshenz/frontend/dist/bilshenz-release.apk
if [[ -f "$APK" ]]; then
  MT=$(stat -c %Y "$APK")
  SZ=$(stat -c %s "$APK")
  echo APK_MTIME=$MT APK_SIZE=$SZ
  if [[ "$MT" -ge {START_EPOCH} ]]; then echo APK_FRESH; fi
else
  echo NO_APK
fi
tail -n 8 /var/log/bilshenz/apk-build.log 2>/dev/null | tr -cd '\\11\\12\\15\\40-\\176' | tail -n 8
"""
        _, stdout, _ = client.exec_command(cmd, timeout=60)
        out = stdout.read().decode("utf-8", errors="replace")
        print(f"=== poll {i+1}/{MAX_MIN} ===")
        print(out)
        sys.stdout.flush()
        if "APK_FRESH" in out and ("BUILD_PID_DEAD" in out or "=== DONE" in out):
            print("APK_READY_FRESH")
            client.close()
            return 0
        if "BUILD FAILED" in out and "BUILD_PID_DEAD" in out:
            print("BUILD_FAILED")
            client.close()
            return 2
        time.sleep(60)

    client.close()
    print("TIMEOUT")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
