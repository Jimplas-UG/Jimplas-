#!/usr/bin/env python3
"""Run full E2E on VPS after deploy."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""#!/usr/bin/env bash
set -e
cd /opt/bilshenz
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
export BRIDGE_TOKEN="$TOKEN"

echo "==> burst close (no 429)"
HITS=0
for i in $(seq 1 25); do
  CODE=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Content-Type: application/json" -H "X-Bridge-Token: $TOKEN" \
    http://127.0.0.1:8766/api/close -d '{"symbol":"BTCUSDT"}')
  if [[ "$CODE" == "429" ]]; then HITS=$((HITS+1)); fi
done
echo "429_hits=$HITS (expect 0)"

echo "==> positions"
curl -s -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions
echo ""

echo "==> health"
curl -s http://127.0.0.1:8766/health | python3 -c "import sys,json; j=json.load(sys.stdin); print('connected',j.get('connected'),'scanner_ws',j.get('scanner_stream',{}).get('ws_connected'))"
echo ""

echo "==> desk manifest"
curl -s http://127.0.0.1:8791/download/manifest.json | python3 -c "import sys,json; j=json.load(sys.stdin); print(j.get('versionName'), j.get('apkPresent'))"

cd /opt/bilshenz/binance_trading_system/python
python3 run_all_tests.py
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=600)
    out = o.read().decode("utf-8", errors="replace")
    err = e.read().decode("utf-8", errors="replace")
    code = o.channel.recv_exit_status()
    c.close()
    print(out)
    if err:
        print(err, file=sys.stderr)
    if "429_hits=0" not in out:
        print("WARN: close rate limit still firing")
    if "ALL_TESTS_PASSED" not in out:
        return 1
    return code


if __name__ == "__main__":
    raise SystemExit(main())
