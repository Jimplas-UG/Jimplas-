#!/usr/bin/env python3
"""Pull latest and restart desk-api (no APK rebuild)."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

HELPER = r"""#!/usr/bin/env bash
set -euo pipefail
cd /opt/bilshenz
git fetch origin
git reset --hard origin/main
git --no-pager log -1 --oneline
cd backend
npm ci 2>/dev/null || npm install
systemctl restart bilshenz-desk-api
sleep 2
systemctl is-active bilshenz-desk-api
ls -lah /opt/bilshenz/frontend/dist/*.apk 2>/dev/null | tail -n 3 || true
curl -s -o /dev/null -w "apk_http:%{http_code}\n" http://127.0.0.1:8791/download/bilshenz.apk
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    with sftp.file("/tmp/bilshenz-restart-desk.sh", "w") as f:
        f.write(HELPER)
    sftp.close()
    _, o, e = c.exec_command("bash /tmp/bilshenz-restart-desk.sh", timeout=300)
    out = o.read().decode()
    err = e.read().decode()
    print(out)
    if err:
        print(err, file=sys.stderr)
    c.close()
    return 0 if "active" in out else 1


if __name__ == "__main__":
    raise SystemExit(main())
