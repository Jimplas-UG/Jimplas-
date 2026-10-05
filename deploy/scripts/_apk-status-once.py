#!/usr/bin/env python3
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set +e
PID=$(cat /var/run/bilshenz-apk-build.pid 2>/dev/null || true)
echo "PID=$PID"
if [ -n "$PID" ] && ps -p "$PID" >/dev/null 2>&1; then
  echo BUILD=running
  ps -p "$PID" -o pid,etime,cmd
else
  echo BUILD=idle
fi
echo ---LOG---
tail -n 40 /var/log/bilshenz/apk-build.log 2>/dev/null || tail -n 40 /var/log/bilshenz/apk-build-nohup.out 2>/dev/null
echo ---APK---
find /opt/bilshenz /var/www /var/lib/bilshenz -name '*.apk' -mtime -3 2>/dev/null | head -30
ls -lah /opt/bilshenz/frontend/android/app/build/outputs/apk/release/ 2>/dev/null | head -20
echo ---HTTP---
for u in /apk /v1/apk /download/bilshenz.apk /bilshenz.apk /static/bilshenz.apk; do
  code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 6 "http://127.0.0.1:8791$u" 2>/dev/null || echo err)
  echo "8791$u -> $code"
done
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR:", err[-1000:])
    c.close()

if __name__ == "__main__":
    main()
