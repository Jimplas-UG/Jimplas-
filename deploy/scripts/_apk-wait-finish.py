#!/usr/bin/env python3
"""Wait until FRA APK build finishes; print download readiness."""
from __future__ import annotations

import time
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

POLL = r"""
pid=$(cat /var/run/bilshenz-apk-build.pid 2>/dev/null || true)
running=0
if [ -n "$pid" ] && ps -p "$pid" >/dev/null 2>&1; then running=1; fi
gradle=$(ps -ef | grep -E 'gradlew assembleRelease' | grep -v grep | wc -l)
tail_line=$(tail -n 3 /var/log/bilshenz/apk-build.log 2>/dev/null || tail -n 3 /var/log/bilshenz/apk-build-nohup.out 2>/dev/null | tr '\n' ' ' | tail -c 200)
apk_mtime=$(stat -c %Y /opt/bilshenz/frontend/dist/bilshenz.apk 2>/dev/null || stat -c %Y /var/www/html/bilshenz.apk 2>/dev/null || echo 0)
size=$(curl -sS -m 3 -o /dev/null -w '%{size_download}' http://127.0.0.1:8791/download/bilshenz.apk || echo 0)
# find newest apk artifact
newest=$(find /opt/bilshenz/frontend -name 'bilshenz*.apk' -o -name 'app-release.apk' 2>/dev/null | xargs ls -lt 2>/dev/null | head -3)
echo "running=$running gradle=$gradle size=$size"
echo "tail=$tail_line"
echo "newest:"
echo "$newest"
# success markers
if grep -qE 'APK ready|BUILD SUCCESSFUL|copied.*bilshenz.apk|DONE' /var/log/bilshenz/apk-build.log 2>/dev/null \
   || grep -qE 'APK ready|BUILD SUCCESSFUL|DONE' /var/log/bilshenz/apk-build-nohup.out 2>/dev/null; then
  if [ "$running" = "0" ]; then echo STATUS=DONE; else echo STATUS=FINISHING; fi
elif [ "$running" = "0" ] && [ "$gradle" = "0" ]; then
  if grep -qiE 'FAIL|error|BUILD FAILED' /var/log/bilshenz/apk-build-nohup.out 2>/dev/null; then echo STATUS=FAILED
  else echo STATUS=IDLE; fi
else
  echo STATUS=BUILDING
fi
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    deadline = time.time() + 25 * 60
    last = ""
    while time.time() < deadline:
        c = paramiko.SSHClient()
        c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
        try:
            _, o, e = c.exec_command(POLL, timeout=30)
            out = o.read().decode("utf-8", "replace")
        finally:
            c.close()
        status_line = [ln for ln in out.splitlines() if ln.startswith("STATUS=")]
        status = status_line[-1].split("=", 1)[-1] if status_line else "?"
        brief = out.strip().splitlines()
        summary = " | ".join(brief[:2] + brief[-1:])
        if summary != last:
            print(summary, flush=True)
            last = summary
        if status in ("DONE", "FAILED", "IDLE"):
            print(out)
            # final download check
            c = paramiko.SSHClient()
            c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
            _, o2, _ = c.exec_command(
                "ls -la --time-style=long-iso $(find /opt/bilshenz /var/www -name 'bilshenz.apk' 2>/dev/null) 2>/dev/null; "
                "curl -sS -m 3 -o /dev/null -w 'download http=%{http_code} size=%{size_download}\n' http://127.0.0.1:8791/download/bilshenz.apk; "
                "stat -c 'apk_mtime=%y' /opt/bilshenz/frontend/dist/bilshenz.apk 2>/dev/null || true",
                timeout=20,
            )
            print(o2.read().decode("utf-8", "replace"))
            c.close()
            raise SystemExit(0 if status == "DONE" else 1)
        time.sleep(20)
    print("TIMEOUT waiting for APK")
    raise SystemExit(2)


if __name__ == "__main__":
    main()
