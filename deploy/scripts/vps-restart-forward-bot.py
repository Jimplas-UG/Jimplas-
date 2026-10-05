#!/usr/bin/env python3
import os, sys
HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
CMD = r"""
systemctl restart bilshenz-forward-bot
sleep 3
systemctl is-active bilshenz-forward-bot bilshenz-binance-api
echo === LOG ===
tail -n 20 /var/log/tradingbot/forward-bot.log 2>/dev/null | tr -cd '\11\12\15\40-\176\n'
echo === GATE ===
curl -sS http://127.0.0.1:8766/health | python3 -c 'import sys,json; h=json.load(sys.stdin); print(h.get("pair_isolation")); sc=h.get("scanner") or {}; print("can_execute", sc.get("can_execute"), "block", sc.get("exec_block"))'
"""
def main():
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err[-1000:])
    c.close()
if __name__ == "__main__":
    raise SystemExit(main())
