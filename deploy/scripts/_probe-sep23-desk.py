#!/usr/bin/env python3
"""Quick FRA desk + APK status probe."""
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
TOK=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/positions
echo
curl -sS http://127.0.0.1:8766/health | /opt/bilshenz/binance_trading_system/python/.venv/bin/python -c "import sys,json;h=json.load(sys.stdin);sc=h.get('scanner') or {};print('can',sc.get('can_execute'),'halt',sc.get('user_exec_halted'),'part',sc.get('partition_usd'),'mode',h.get('mode'),'conn',h.get('connected'))"
pid=$(cat /var/run/bilshenz-apk-build.pid 2>/dev/null || true)
if [ -n "$pid" ] && ps -p "$pid" >/dev/null 2>&1; then echo BUILDING pid=$pid; else echo APK_IDLE pid=${pid:-none}; fi
ps -ef | grep -E 'gradlew|expo prebuild' | grep -v grep | head -3 || true
tail -n 12 /var/log/bilshenz/apk-build-nohup.out 2>/dev/null || true
curl -sS -m 3 -o /dev/null -w 'apk_http=%{http_code} size=%{size_download}\n' http://127.0.0.1:8791/download/bilshenz.apk || true
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=40)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err.encode("ascii", "replace").decode("ascii")[-400:])
    c.close()


if __name__ == "__main__":
    main()
