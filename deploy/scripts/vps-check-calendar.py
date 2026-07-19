#!/usr/bin/env python3
"""Print live trade-calendar + sample recent deals from VPS bridge."""
import json
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    cmd = r"""
grep TRADE_HISTORY /etc/bilshenz.env || true
echo '---CAL---'
curl -s 'http://127.0.0.1:8766/api/trade-calendar?days=40'
echo
echo '---DEALS---'
curl -s 'http://127.0.0.1:8766/api/deals?limit=15' | python3 -c 'import sys,json;d=json.load(sys.stdin);rows=d.get("deals") or d.get("history") or d;print(json.dumps(rows[:8] if isinstance(rows,list) else d, indent=2)[:2500])'
"""
    _, stdout, stderr = client.exec_command(cmd, timeout=90)
    print(stdout.read().decode("utf-8", "replace"))
    err = stderr.read().decode("utf-8", "replace")
    if err.strip():
        print(err, file=sys.stderr)
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
