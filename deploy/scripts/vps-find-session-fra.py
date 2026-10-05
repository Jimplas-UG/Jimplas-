#!/usr/bin/env python3
"""Find stored Binance session / keys on FRA (lengths only)."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
echo '=== session store ==='
ls -la /var/lib/bilshenz/ 2>/dev/null || echo no_var_lib
find /var/lib /opt/bilshenz /tmp -name '*session*' 2>/dev/null | head -40
python3 <<'PY'
from pathlib import Path
import json
cands = list(Path('/var/lib/bilshenz').glob('*')) if Path('/var/lib/bilshenz').exists() else []
cands += list(Path('/opt/bilshenz/binance_trading_system/python').glob('*session*'))
for p in cands:
    print('FILE', p, p.stat().st_size if p.is_file() else 'dir')
    if p.is_file() and p.suffix in ('.json','.enc','.dat','') or 'session' in p.name:
        try:
            raw = p.read_bytes()[:200]
            print('  head', raw[:80])
        except Exception as e:
            print('  readerr', e)
        try:
            j=json.loads(p.read_text())
            def walk(o, prefix=''):
                if isinstance(o, dict):
                    for k,v in o.items():
                        ku=str(k).lower()
                        if any(x in ku for x in ('key','secret','token')):
                            if isinstance(v,str):
                                print(f'  {prefix}{k}=len{len(v)}')
                            else:
                                print(f'  {prefix}{k}=type{type(v).__name__}')
                        else:
                            walk(v, prefix+k+'.')
                elif isinstance(o, list) and o:
                    walk(o[0], prefix+'[0].')
            walk(j)
        except Exception:
            pass
PY
echo '=== bilshenz.env full keys list ==='
grep -E '^[A-Z0-9_]+=' /etc/bilshenz.env | cut -d= -f1 | sort
echo '=== env backups ==='
ls -la /etc/bilshenz.env* /etc/*.env.bak 2>/dev/null
# digitalocean metadata? no
# check journal for previous key_len
grep -E 'key_len|api_key|BINANCE_API' /var/log/bilshenz/*.log 2>/dev/null | tail -n 20 || true
echo '=== forward demo script ==='
ls -la /opt/bilshenz/backend/scripts/run-forward-demo-30d.ts 2>/dev/null
head -n 40 /opt/bilshenz/deploy/tradingbot.env.example 2>/dev/null
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
