#!/usr/bin/env python3
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
echo === LIB ===
ls -la /var/lib/bilshenz/ 2>/dev/null || true
echo === ENV KEYS ===
grep -E 'BINANCE_API|SESSION|TESTNET' /etc/bilshenz.env | sed 's/\(KEY\|SECRET\|TOKEN\)=.*/\1=***/'
echo === SESSION JSON ===
python3 - <<'PY'
import json, os
p='/var/lib/bilshenz/binance-session.json'
print('exists', os.path.isfile(p))
if os.path.isfile(p):
  j=json.load(open(p))
  print({k: ('set' if j.get(k) else j.get(k)) for k in ('api_key','api_secret','testnet','saved_at','mode')})
PY
echo === LOG ===
journalctl -u bilshenz-binance-api --since '10 min ago' --no-pager 2>/dev/null | tr -cd '\11\12\15\40-\176\n' | tail -n 80
"""


def main() -> int:
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=25, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=45)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err)
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
