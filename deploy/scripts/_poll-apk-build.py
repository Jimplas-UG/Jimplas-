#!/usr/bin/env python3
"""Poll FRA APK build status."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
PID=$(cat /var/run/bilshenz-apk-build.pid 2>/dev/null || echo none)
echo PID=$PID
if [[ "$PID" != "none" ]] && ps -p "$PID" >/dev/null 2>&1; then
  echo RUNNING=1
  ps -p "$PID" -o pid,etime,cmd
else
  echo RUNNING=0
fi
echo ---LOG_TAIL---
tail -n 30 /var/log/bilshenz/apk-build.log 2>/dev/null || tail -n 30 /var/log/bilshenz/apk-build-nohup.out 2>/dev/null || true
echo ---APK---
ls -lah /opt/bilshenz/frontend/dist/*.apk 2>/dev/null || echo no_apk_yet
grep -E 'BUILD SUCCESSFUL|BUILD FAILED|FRA APK ready|error|Error|FAILED' /var/log/bilshenz/apk-build.log 2>/dev/null | tail -n 15 || true
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=40)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    c.close()

if __name__ == "__main__":
    main()
