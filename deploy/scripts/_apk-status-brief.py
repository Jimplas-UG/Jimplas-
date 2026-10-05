#!/usr/bin/env python3
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"

CMD = r"""
pid=$(cat /var/run/bilshenz-apk-build.pid 2>/dev/null || true)
if [ -n "$pid" ] && ps -p "$pid" >/dev/null 2>&1; then
  echo "BUILDING pid=$pid"
else
  echo "NOT_RUNNING pid=${pid:-none}"
fi
ps -ef | grep -E 'gradlew|expo prebuild|npm ci' | grep -v grep | head -5
curl -sS -m 3 -o /dev/null -w 'apk_http=%{http_code} size=%{size_download}\n' http://127.0.0.1:8791/download/bilshenz.apk || true
tail -n 15 /var/log/bilshenz/apk-build.log 2>/dev/null || tail -n 15 /var/log/bilshenz/apk-build-nohup.out 2>/dev/null || true
curl -sS -m 3 http://127.0.0.1:8766/health | """ + PY + r""" -c 'import sys,json;h=json.load(sys.stdin);sc=h.get("scanner_stream") or {};ud=h.get("user_data_stream") or {};tk=h.get("tick_stream") or {};print("streams", "tick", tk.get("ws_connected"), "scanner_ws", sc.get("ws_connected"), "rest", sc.get("rest_active"), "user", ud.get("ws_connected"))'
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=30)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print(err[-500:])
    c.close()

if __name__ == "__main__":
    main()
