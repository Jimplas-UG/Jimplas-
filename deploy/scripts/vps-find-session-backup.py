#!/usr/bin/env python3
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
echo === SEARCH SESSION BACKUPS ===
find /var /opt /root /tmp -name '*binance*session*' 2>/dev/null | head -n 40
find /var /opt /root -name '*session*.json*' 2>/dev/null | head -n 40
ls -la /var/lib/bilshenz/ /var/lib/bilshenz/*.bak /var/lib/bilshenz/*~ 2>/dev/null
echo === DESK MAY HAVE KEYS ===
grep -RIl 'api_secret\|apiKey\|API_SECRET' /opt/bilshenz/backend /var/lib/bilshenz 2>/dev/null | head -n 20
"""


def main() -> int:
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=25, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err)
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
