#!/usr/bin/env python3
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
# Find where python logs go
systemctl cat bilshenz-binance-api | head -n 40
echo === APP LOGS ===
ls -lt /var/log/tradingbot /var/log/bilshenz 2>/dev/null | head -n 20
tail -n 80 /var/log/tradingbot/binance-api.log 2>/dev/null | tr -cd '\11\12\15\40-\176\n' || true
tail -n 80 /var/log/bilshenz/binance-api.log 2>/dev/null | tr -cd '\11\12\15\40-\176\n' || true
# Force env login via attach endpoint if exists
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
echo === ATTACH ===
curl -sS -X POST -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/attach || true
echo
echo === HEALTH ===
curl -sS http://127.0.0.1:8766/health | python3 -c 'import sys,json; h=json.load(sys.stdin); s=h.get("scanner") or {}; print({"mode":h.get("mode"),"connected":h.get("connected"),"can_execute":s.get("can_execute"),"exec_block":s.get("exec_block"),"testnet":h.get("testnet")})'
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
