#!/usr/bin/env python3
"""Verify new droplet health locally + publicly."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import paramiko

HOST = "161.35.112.53"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set -e
systemctl is-active bilshenz-binance-api bilshenz-desk-api
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2-)
echo TOKEN_LEN=${#TOKEN}
curl -sS --max-time 10 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health
echo
curl -sS --max-time 10 http://127.0.0.1:8791/health
echo
python3 - <<'PY'
from pathlib import Path
lines = Path('/etc/bilshenz.env').read_text().splitlines()
for k in ['BINANCE_API_KEY','BINANCE_API_SECRET','BINANCE_TESTNET','FORWARD_DRY_RUN','SCANNER_EXEC']:
    for line in lines:
        if line.startswith(k + '='):
            v = line.split('=', 1)[1].strip().strip('"').strip("'")
            if k.startswith('BINANCE_API'):
                print(k, 'SET' if len(v) >= 8 else 'EMPTY')
            else:
                print(k, v)
            break
    else:
        print(k, 'MISSING')
src = Path('/opt/bilshenz/binance_trading_system/python/momentum_scanner.py').read_text()
print('paired_hold', 'PAIR_INVALIDATION_PCT' in src and '_short_underwater' in src)
PY
ufw status numbered | head -20
"""


def main() -> int:
    key = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=key, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    print(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        print("STDERR:", err[-1000:])
    c.close()

    for url in [
        f"http://{HOST}:8766/health",
        f"http://{HOST}:8791/health",
    ]:
        try:
            with urllib.request.urlopen(url, timeout=12) as r:
                body = r.read()[:400].decode("utf-8", errors="replace")
            print("PUBLIC", url, body)
        except Exception as ex:
            print("PUBLIC", url, "FAIL", ex)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
