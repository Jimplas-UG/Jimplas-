#!/usr/bin/env python3
"""Diagnose FRA keys + forward-bot unit + APK build status."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
echo '=== ENV KEYS (masked) ==='
python3 <<'PY'
from pathlib import Path
for line in Path('/etc/bilshenz.env').read_text().splitlines():
    if not line or '=' not in line or line.lstrip().startswith('#'):
        continue
    k,v=line.split('=',1)
    ku=k.upper()
    if any(x in ku for x in ('KEY','SECRET','TOKEN','PASSWORD')):
        vv=v.strip().strip('"').strip("'")
        print(f'{k}=len{len(vv)} prefix={vv[:4]}...' if vv else f'{k}=EMPTY')
    elif k in ('BINANCE_TESTNET','BINANCE_FORCE_TESTNET','SCANNER_EXEC','FORWARD_DRY_RUN','BINANCE_PAPER'):
        print(line)
PY
echo '=== FORWARD UNIT ==='
systemctl cat bilshenz-forward-bot 2>&1 | head -n 80
echo '=== ENV FILES ==='
ls -la /etc/bilshenz.env /etc/tradingbot.env /etc/default/bilshenz* 2>&1 | head
echo '=== KEY BACKUPS ==='
ls -la /root 2>/dev/null | head -40
find /opt/bilshenz /root /var/backups -maxdepth 3 -type f \( -name '*.env*' -o -name '*session*' -o -name '*binance*' \) 2>/dev/null | head -40
echo '=== BUILD ==='
ps aux | grep -E 'build-apk|gradlew|expo' | grep -v grep | head
tail -n 20 /var/log/bilshenz/apk-build.log 2>/dev/null || true
tail -n 20 /var/log/bilshenz/apk-build-nohup.out 2>/dev/null || true
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-1500:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
