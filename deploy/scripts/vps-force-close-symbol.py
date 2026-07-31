#!/usr/bin/env python3
"""Force-flatten a stuck hedge pair on VPS."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
SYMBOL = os.environ.get("CLOSE_SYMBOL", "MUSDT")

CMD = r"""#!/usr/bin/env bash
set -euo pipefail
SYM='""" + SYMBOL + r"""'
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
echo === BEFORE ===
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions
echo
for side in LONG SHORT; do
  echo === CLOSE_$side ===
  curl -sS -X POST -H "Content-Type: application/json" -H "X-Bridge-Token: $TOKEN" \
    http://127.0.0.1:8766/api/close \
    -d "{\"symbol\":\"$SYM\",\"position_side\":\"$side\"}"
  echo
done
echo === CLOSE_PAIR ===
curl -sS -X POST -H "Content-Type: application/json" -H "X-Bridge-Token: $TOKEN" \
  http://127.0.0.1:8766/api/close \
  -d "{\"symbol\":\"$SYM\",\"close_pair\":true}"
echo
sleep 2
echo === CLOSE_ALL ===
curl -sS -X POST -H "Content-Type: application/json" -H "X-Bridge-Token: $TOKEN" \
  http://127.0.0.1:8766/api/close-all -d '{}'
echo
sleep 2
echo === AFTER ===
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions
echo
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=120)
    print(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        print(err, file=sys.stderr)
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
