#!/usr/bin/env python3
"""Test close via desk proxy (mobile production path)."""
import os, sys
HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
CMD = r"""#!/usr/bin/env bash
set -e
DESK_KEY=$(grep -E '^DESK_API_KEY=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
HITS=0
for i in $(seq 1 20); do
  CODE=$(curl -s -o /tmp/desk_close.txt -w '%{http_code}' -X POST \
    -H "Content-Type: application/json" -H "Authorization: Bearer $DESK_KEY" \
    http://127.0.0.1:8791/v1/binance/api/close -d '{"symbol":"BTCUSDT"}')
  if [ "$CODE" = "429" ]; then HITS=$((HITS+1)); fi
done
echo "desk_proxy_429_hits=$HITS"
cat /tmp/desk_close.txt
echo ""
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
