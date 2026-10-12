#!/usr/bin/env python3
"""Egress IP + mainnet used-weight header (does not touch the banned testnet host)."""
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
echo "egress4 $(curl -4 -s --max-time 8 https://api.ipify.org)"
echo "egress6 $(curl -6 -s --max-time 8 https://api64.ipify.org || echo none)"
getent hosts testnet.binancefuture.com fapi.binance.com
echo '--- mainnet /fapi/v1/time headers'
curl -4 -s -D - -o /dev/null --max-time 8 https://fapi.binance.com/fapi/v1/time | grep -iE "^HTTP|weight|retry"
echo '--- bridge base url / testnet env'
grep -hE "^(BINANCE_TESTNET|TESTNET|BINANCE_BASE|SCANNER_)" /etc/bilshenz.env 2>/dev/null | sed -E 's/(KEY|SECRET)=.*/\1=***/'
echo '--- weight lines since 15:33 (should be none while banned)'
grep -hE "used weight|418 IP ban|Binance 429" /var/log/bilshenz/*.log | awk '$1 >= "2026-10-12T15:33"' | tail -n 5
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
