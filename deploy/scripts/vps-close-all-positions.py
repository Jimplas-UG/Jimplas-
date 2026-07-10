#!/usr/bin/env python3
"""Deploy binance bridge fix and close all open positions on VPS."""
import json
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""#!/usr/bin/env bash
set -euo pipefail
cd /opt/bilshenz
git fetch origin
git reset --hard origin/main
git log -1 --oneline

systemctl restart bilshenz-binance-api
systemctl restart bilshenz-desk-api
sleep 5
systemctl is-active bilshenz-binance-api bilshenz-desk-api

# Bridge token for local close-all
TOKEN=""
if [[ -f /etc/bilshenz.env ]]; then
  TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
fi
if [[ -z "$TOKEN" ]]; then
  TOKEN=$(grep -E '^DESK_API_KEY=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
fi

echo "---POSITIONS_BEFORE---"
curl -s -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions || true
echo ""

echo "---CLOSE_ALL---"
curl -s -X POST -H "Content-Type: application/json" -H "X-Bridge-Token: $TOKEN" \
  http://127.0.0.1:8766/api/close-all -d '{}'
echo ""

echo "---POSITIONS_AFTER---"
curl -s -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions || true
echo ""
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=300)
    out = o.read().decode("utf-8", errors="replace")
    err = e.read().decode("utf-8", errors="replace")
    code = o.channel.recv_exit_status()
    c.close()
    print(out)
    if err:
        print(err, file=sys.stderr)
    if "---CLOSE_ALL---" in out:
        block = out.split("---CLOSE_ALL---", 1)[-1].split("---POSITIONS_AFTER---")[0].strip()
        try:
            j = json.loads(block)
            print("\nCLOSE_ALL_RESULT:", json.dumps(j, indent=2))
            if not j.get("ok"):
                return 1
        except json.JSONDecodeError:
            print("WARN: could not parse close-all JSON:", block[:500])
    return code


if __name__ == "__main__":
    raise SystemExit(main())
