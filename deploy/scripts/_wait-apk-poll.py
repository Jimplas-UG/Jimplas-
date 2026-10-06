#!/usr/bin/env python3
"""Poll FRA APK build until idle; print download URL/size."""
from pathlib import Path
import time

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
pid=$(cat /var/run/bilshenz-apk-build.pid 2>/dev/null || true)
if [ -n "$pid" ] && ps -p "$pid" >/dev/null 2>&1; then
  echo BUILDING pid=$pid
  ps -p "$pid" -o etime= 2>/dev/null || true
  tail -n 5 /var/log/bilshenz/apk-build.log 2>/dev/null || tail -n 5 /var/log/bilshenz/apk-build-nohup.out 2>/dev/null || true
else
  echo DONE
  ls -la /opt/bilshenz/frontend/android/app/build/outputs/apk/release/*.apk 2>/dev/null || true
  ls -la /var/www/bilshenz/bilshenz.apk 2>/dev/null || ls -la /opt/bilshenz/frontend/dist/bilshenz.apk 2>/dev/null || true
  curl -sS -m 3 -o /dev/null -w 'apk_http=%{http_code} size=%{size_download}\n' http://127.0.0.1:8791/download/bilshenz.apk || true
  grep -E 'APK_READY|BUILD_OK|FAILED|error' /var/log/bilshenz/apk-build-nohup.out 2>/dev/null | tail -n 8 || true
fi
"""


def probe(c):
    _, o, e = c.exec_command(CMD, timeout=30)
    out = o.read().decode("utf-8", "replace")
    e.read()
    return out


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    for i in range(60):
        out = probe(c)
        print(f"--- poll {i} ---")
        print(out.encode("ascii", "replace").decode("ascii")[:800])
        if out.strip().startswith("DONE"):
            print("APK_POLL_DONE")
            break
        time.sleep(30)
    else:
        print("APK_POLL_TIMEOUT")
    c.close()


if __name__ == "__main__":
    main()
