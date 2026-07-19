#!/usr/bin/env python3
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""#!/usr/bin/env bash
set -e
cd /opt/bilshenz
git log -1 --oneline
grep -n "_TRADE_PATHS" binance_trading_system/python/main.py | head -2
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
echo "TOKEN_LEN=${#TOKEN}"
HITS=0
CODES=""
for i in $(seq 1 20); do
  CODE=$(curl -s -o /tmp/close_body.txt -w '%{http_code}' -X POST \
    -H "Content-Type: application/json" -H "X-Bridge-Token: $TOKEN" \
    http://127.0.0.1:8766/api/close -d '{"symbol":"BTCUSDT"}')
  CODES="$CODES $CODE"
  if [ "$CODE" = "429" ]; then HITS=$((HITS+1)); fi
done
echo "429_hits=$HITS"
echo "codes:$CODES"
echo "last_body:"
cat /tmp/close_body.txt
echo ""
curl -s -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions
echo ""
curl -s http://127.0.0.1:8766/health | head -c 400
echo ""
systemctl is-active bilshenz-binance-api || true
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
    out = o.read().decode("utf-8", errors="replace")
    err = e.read().decode("utf-8", errors="replace")
    code = o.channel.recv_exit_status()
    print(out)
    if err:
        print(err, file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
