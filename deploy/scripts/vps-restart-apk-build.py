#!/usr/bin/env python3
"""Start VPS APK build via a remote helper script (avoids self-pkill)."""
import os
import sys
import time

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

HELPER = r"""#!/usr/bin/env bash
set -euo pipefail
export GIT_PAGER=cat PAGER=cat
cd /opt/bilshenz
git fetch origin
git reset --hard origin/main
git --no-pager log -1 --oneline
chmod +x deploy/ubuntu/build-apk-on-vps.sh
# Stop prior build by PID file only
if [[ -f /var/run/bilshenz-apk-build.pid ]]; then
  old=$(cat /var/run/bilshenz-apk-build.pid || true)
  if [[ -n "${old:-}" ]] && kill -0 "$old" 2>/dev/null; then
    kill "$old" 2>/dev/null || true
    sleep 2
    kill -9 "$old" 2>/dev/null || true
  fi
fi
# Stop hung gradle if any (by exact java main class via jps if available)
if command -v jps >/dev/null 2>&1; then
  jps -l | awk '/GradleWrapperMain/{print $1}' | xargs -r kill 2>/dev/null || true
fi
: > /var/log/bilshenz/apk-build.out
setsid bash /opt/bilshenz/deploy/ubuntu/build-apk-on-vps.sh >>/var/log/bilshenz/apk-build.out 2>&1 < /dev/null &
echo $! > /var/run/bilshenz-apk-build.pid
echo START_OK pid=$(cat /var/run/bilshenz-apk-build.pid)
sleep 5
pid=$(cat /var/run/bilshenz-apk-build.pid)
if kill -0 "$pid" 2>/dev/null; then echo BUILD_RUNNING; else echo BUILD_EXITED_EARLY; fi
tail -n 20 /var/log/bilshenz/apk-build.out | tr -cd '\11\12\15\40-\176'
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = client.open_sftp()
    with sftp.file("/tmp/bilshenz-start-apk.sh", "w") as f:
        f.write(HELPER)
    sftp.chmod("/tmp/bilshenz-start-apk.sh", 0o755)
    sftp.close()

    _, stdout, stderr = client.exec_command("bash /tmp/bilshenz-start-apk.sh", timeout=180)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    sys.stdout.write(out)
    if err.strip():
        sys.stderr.write(err)
    client.close()
    return 0 if "START_OK" in out else 1


if __name__ == "__main__":
    raise SystemExit(main())
