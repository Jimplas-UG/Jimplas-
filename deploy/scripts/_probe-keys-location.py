#!/usr/bin/env python3
"""Find where live Binance keys live on FRA after Connect."""
from __future__ import annotations

from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set -e
systemctl cat bilshenz-binance-api | head -60
echo '--- env file keys (names only) ---'
for f in /etc/bilshenz.env /opt/bilshenz/.env /opt/bilshenz/binance_trading_system/python/.env; do
  [ -f "$f" ] || continue
  echo "FILE $f"
  grep -E '^[A-Z0-9_]+=' "$f" | cut -d= -f1 | head -40
done
echo '--- session files ---'
find /opt/bilshenz /var/lib/bilshenz /tmp -name '*session*' -o -name '*keys*' 2>/dev/null | head -40
echo '--- health user ---'
curl -sS -m 3 http://127.0.0.1:8766/health | python3 -c 'import sys,json; h=json.load(sys.stdin); print({k:h.get(k) for k in ("connected","testnet","ok")}); print("user",h.get("user_data_stream")); print("scanner",{k:(h.get("scanner_stream") or {}).get(k) for k in ("ws_connected","rest_active","ws_ticks","rest_ticks","last_error")})'
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=40)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print(err[-1500:])
    c.close()

if __name__ == "__main__":
    main()
