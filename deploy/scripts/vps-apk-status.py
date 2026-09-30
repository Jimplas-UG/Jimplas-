#!/usr/bin/env python3
"""Check whether FRA APK build is ready."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
set +e
echo "=== apk process ==="
ps -ef | grep -E 'build-apk-fra|gradlew|expo prebuild|eas-cli|npm ci' | grep -v grep | head -n 8
echo "=== pid ==="
if [ -f /var/run/bilshenz-apk-build.pid ]; then
  PID=$(cat /var/run/bilshenz-apk-build.pid)
  echo pid=$PID
  if ps -p "$PID" >/dev/null 2>&1; then echo BUILD_RUNNING; else echo BUILD_NOT_RUNNING; fi
else
  echo no_pid_file
  echo BUILD_NOT_RUNNING
fi
echo "=== apk files ==="
find /opt/bilshenz /var/www /root -name '*.apk' -mtime -3 2>/dev/null | head -n 15
ls -lt /opt/bilshenz/frontend/android/app/build/outputs/apk/release/ 2>/dev/null | head -n 8
echo "=== log tail ==="
if [ -f /var/log/bilshenz/apk-build.log ]; then tail -n 30 /var/log/bilshenz/apk-build.log
elif [ -f /var/log/bilshenz/apk-build-nohup.out ]; then tail -n 30 /var/log/bilshenz/apk-build-nohup.out
else echo no_log; fi
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    sys.stdout.buffer.write(o.read())
    err = e.read()
    if err.strip():
        sys.stderr.buffer.write(err[-800:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
