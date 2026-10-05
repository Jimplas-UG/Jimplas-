#!/usr/bin/env python3
"""Force Frankfurt bridge into Binance Futures TESTNET (no mainnet fallback)."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)

    sftp = c.open_sftp()
    sftp.put(str(ROOT / "binance_trading_system/python/main.py"), "/opt/bilshenz/binance_trading_system/python/main.py")
    sftp.close()

    CMD = r"""
set -euo pipefail
python3 <<'PY'
from pathlib import Path
p = Path('/etc/bilshenz.env')
want = {
  'BINANCE_TESTNET': '1',
  'BINANCE_FORCE_TESTNET': '1',
  'BINANCE_FORCE_MAINNET': '0',
  'BINANCE_PAPER': '0',
  'FORWARD_DRY_RUN': '0',
  'SCANNER_EXEC': '1',
}
lines = p.read_text().splitlines()
out, seen = [], set()
for line in lines:
    if '=' in line and not line.startswith('#'):
        k = line.split('=', 1)[0]
        if k in want:
            out.append(f'{k}={want[k]}')
            seen.add(k)
            continue
    out.append(line)
for k, v in want.items():
    if k not in seen:
        out.append(f'{k}={v}')
p.write_text('\n'.join(out) + '\n')
p.chmod(0o600)
print('env_ok')
for k in sorted(want):
    print(k, want[k])
PY
rm -f /var/lib/bilshenz/binance-session.json \
      /opt/bilshenz/binance_trading_system/python/.binance_session.json 2>/dev/null || true
systemctl restart bilshenz-binance-api
sleep 9
systemctl is-active bilshenz-binance-api
grep -E '^(BINANCE_TESTNET|BINANCE_FORCE_TESTNET)=' /etc/bilshenz.env
curl -sS --max-time 12 http://127.0.0.1:8766/health > /tmp/h.json
python3 - <<'PY'
import json
d=json.load(open('/tmp/h.json'))
s=d.get('scanner') or {}
print('health_mode', d.get('mode'), 'connected', d.get('connected'), 'exec', s.get('can_execute'), 'block', s.get('exec_block'))
PY
grep -E 'testnet|TESTNET|mainnet|login ok' /var/log/bilshenz/binance-api.log | tail -n 15
"""
    _, o, e = c.exec_command(CMD, timeout=120)
    print(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        print("STDERR:", err[-2000:])
    code = o.channel.recv_exit_status()
    c.close()
    try:
        with urllib.request.urlopen(f"http://{HOST}:8766/health", timeout=12) as r:
            d = json.loads(r.read().decode())
        print("PUBLIC mode=", d.get("mode"), "connected=", d.get("connected"))
    except Exception as ex:
        print("PUBLIC_FAIL", ex)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
