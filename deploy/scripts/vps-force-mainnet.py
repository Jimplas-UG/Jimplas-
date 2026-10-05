#!/usr/bin/env python3
"""Force Frankfurt bridge onto Binance Futures MAINNET (no strategy changes)."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set -euo pipefail
python3 <<'PY'
from pathlib import Path
p = Path('/etc/bilshenz.env')
want = {
  'BINANCE_TESTNET': '0',
  'BINANCE_FORCE_TESTNET': '0',
  'BINANCE_FORCE_MAINNET': '1',
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
# lengths only — never print secrets
d = {}
for line in p.read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        a,b=line.split('=',1); d[a]=b.strip().strip('"').strip("'")
print('key_len', len(d.get('BINANCE_API_KEY','')))
print('secret_len', len(d.get('BINANCE_API_SECRET','')))
PY
rm -f /var/lib/bilshenz/binance-session.json \
      /opt/bilshenz/binance_trading_system/python/.binance_session.json 2>/dev/null || true
systemctl restart bilshenz-binance-api
sleep 10
systemctl is-active bilshenz-binance-api
grep -E '^(BINANCE_TESTNET|BINANCE_FORCE_MAINNET|BINANCE_FORCE_TESTNET|FORWARD_DRY_RUN|SCANNER_EXEC)=' /etc/bilshenz.env
curl -sS -o /dev/null -w 'mainnet_ping=%{http_code}\n' --max-time 12 https://fapi.binance.com/fapi/v1/ping || true
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS --max-time 15 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json || true
curl -sS --max-time 15 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/status > /tmp/st.json || true
python3 <<'PY'
import json
from pathlib import Path
h=json.loads(Path('/tmp/h.json').read_text() or '{}')
st=json.loads(Path('/tmp/st.json').read_text() or '{}')
s=h.get('scanner') or {}
acct=st.get('account') or {}
print('health_mode', h.get('mode'), 'testnet', h.get('testnet'), 'connected', h.get('connected'))
print('status_mode', st.get('mode'), 'testnet', st.get('testnet'), 'connected', st.get('connected'))
print('exec', s.get('can_execute'), 'block', s.get('exec_block'), 'strategy', s.get('strategy_id'))
print('bal', acct.get('balance'), 'server', acct.get('server'))
if st.get('error'): print('status_error', str(st.get('error'))[:160])
if h.get('error'): print('health_error', str(h.get('error'))[:160])
PY
grep -E 'mainnet|testnet|FORCE_MAINNET|login ok|invalid api' /var/log/bilshenz/binance-api.log 2>/dev/null | tail -n 20 || true
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=120)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
