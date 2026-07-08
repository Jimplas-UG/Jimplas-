#!/usr/bin/env python3
"""Poll VPS until APK is published or build fails."""
import os
import sys
import time

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
MAX_MIN = int(os.environ.get("POLL_MINUTES", "55"))


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)

    for i in range(MAX_MIN):
        cmd = r"""
curl -s --max-time 5 http://127.0.0.1:8791/download; echo
ls -lh /opt/bilshenz/frontend/dist/bilshenz-release.apk 2>/dev/null || echo NO_APK
if [[ -f /var/run/bilshenz-apk-build.pid ]]; then
  pid=$(cat /var/run/bilshenz-apk-build.pid)
  if kill -0 "$pid" 2>/dev/null; then echo BUILD_PID_ALIVE=$pid; else echo BUILD_PID_DEAD=$pid; fi
else
  echo NO_PID_FILE
fi
pgrep -c -f '/opt/bilshenz/deploy/ubuntu/build-apk-on-vps.sh' || true
tail -n 12 /var/log/bilshenz/apk-build.log 2>/dev/null | tr -cd '\11\12\15\40-\176' | tail -n 12
"""
        _, stdout, _ = client.exec_command(cmd, timeout=60)
        out = stdout.read().decode("utf-8", errors="replace")
        print(f"=== poll {i+1}/{MAX_MIN} ===")
        print(out)
        sys.stdout.flush()
        if '"ok":true' in out.replace(" ", "") or '"ok": true' in out:
            if "bilshenz-release.apk" in out and "NO_APK" not in out.splitlines()[1]:
                print("APK_READY")
                client.close()
                return 0
        if "BUILD FAILED" in out or "FAILURE:" in out:
            # Only fail if process is dead
            if "BUILD_PID_DEAD" in out or "NO_PID_FILE" in out:
                print("BUILD_FAILED")
                client.close()
                return 2
        if "=== DONE" in out and "bilshenz-release.apk" in out:
            print("APK_READY")
            client.close()
            return 0
        time.sleep(60)

    client.close()
    print("TIMEOUT")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
