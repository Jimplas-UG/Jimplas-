#!/usr/bin/env python3
"""Enable REST_BAN_FILE for the bridge and seed the active Binance 418 ban (Retry-After)."""
import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
BAN_START = sys.argv[1] if len(sys.argv) > 1 else "2026-10-12T15:33:01Z"
RETRY_AFTER = int(sys.argv[2]) if len(sys.argv) > 2 else 9355

CMD = rf"""
set -e
systemctl cat bilshenz-binance-api --no-pager | grep -E "EnvironmentFile" || true
mkdir -p /var/lib/bilshenz
grep -q '^REST_BAN_FILE=' /etc/bilshenz.env || echo 'REST_BAN_FILE=/var/lib/bilshenz/rest-ban.json' >> /etc/bilshenz.env
grep '^REST_BAN_FILE=' /etc/bilshenz.env
until=$(( $(date -u -d '{BAN_START}' +%s) + {RETRY_AFTER} ))
now=$(date -u +%s)
if [ "$until" -gt "$now" ]; then
  echo "{{\"until_epoch\": $until, \"host\": \"testnet.binancefuture.com\"}}" > /var/lib/bilshenz/rest-ban.json
fi
cat /var/lib/bilshenz/rest-ban.json 2>/dev/null || echo 'no active ban'
echo "left_s=$(( until - now ))"
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err[-600:])
    c.close()


if __name__ == "__main__":
    main()
