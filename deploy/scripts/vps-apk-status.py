#!/usr/bin/env python3
import os, sys, json
HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
CMD = r"""#!/usr/bin/env bash
MANIFEST=/opt/bilshenz/frontend/dist/release-manifest.json
if [ -f "$MANIFEST" ]; then cat "$MANIFEST"; fi
grep -E '=== DONE |FATAL:|BUILD FAILED' /var/log/bilshenz/apk-build.log | tail -n 5
if [ -f /var/run/bilshenz-apk-build.pid ]; then
  pid=$(cat /var/run/bilshenz-apk-build.pid)
  kill -0 "$pid" 2>/dev/null && echo BUILD_ALIVE || echo BUILD_DEAD
else echo NO_PID; fi
tail -n 8 /var/log/bilshenz/apk-build.log | tr -cd '\11\12\15\40-\176'
curl -s http://127.0.0.1:8791/download/manifest.json
"""
def main():
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username='root', password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    print(o.read().decode())
    c.close()
if __name__ == '__main__':
    main()
