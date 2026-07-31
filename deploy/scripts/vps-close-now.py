#!/usr/bin/env python3
"""Close all open Binance positions on VPS (no redeploy)."""
import json
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""#!/usr/bin/env bash
set -euo pipefail
TOKEN=""
if [[ -f /etc/bilshenz.env ]]; then
  TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
fi
if [[ -z "$TOKEN" ]]; then
  TOKEN=$(grep -E '^DESK_API_KEY=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
fi

echo === BEFORE ===
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions
echo
echo === STATUS ===
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health | python3 -c 'import sys,json; h=json.load(sys.stdin); s=h.get("scanner") or {}; print(json.dumps({"mode":h.get("mode"),"active":s.get("active_symbol"),"pending":s.get("pending_count"),"best":s.get("best_pending"),"can_execute":s.get("can_execute")},indent=2))'
echo
echo === CLOSE_ALL ===
curl -sS -X POST -H "Content-Type: application/json" -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/close-all -d '{}'
echo
sleep 2
echo === AFTER ===
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions
echo
echo === SCANNER_AFTER ===
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health | python3 -c 'import sys,json; h=json.load(sys.stdin); s=h.get("scanner") or {}; print(json.dumps({"active":s.get("active_symbol"),"pending":s.get("pending_count"),"best":s.get("best_pending"),"watchlist":s.get("watchlist")},indent=2))'
echo
echo === RECENT_LOG ===
journalctl -u bilshenz-binance-api --no-pager -n 80 2>/dev/null | grep -E 'STORJ|LONG1|SHORT1|SHORT2|pending|blocked|EXEC_|scanner LONG|adopt|flatten|PULLBACK|SMART|orphan|demote|best_pending' | tail -n 50 || true
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
    c.close()
    print(out)
    if err.strip():
        print(err, file=sys.stderr)
    return 0 if "=== CLOSE_ALL ===" in out else 1


if __name__ == "__main__":
    raise SystemExit(main())
