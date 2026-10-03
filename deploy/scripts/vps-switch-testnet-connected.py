#!/usr/bin/env python3
"""Switch FRA to Binance Futures TESTNET, keep $100 partition + exec armed, verify connected."""
from __future__ import annotations

from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"

CMD = r'''
set -euo pipefail
python3 <<'PY'
from pathlib import Path
import json
p = Path('/etc/bilshenz.env')
raw = p.read_text(encoding='utf-8')
if raw.count('\n') < 10 or raw.count('\\n') > 5:
    raise SystemExit(f'REFUSE_SMASHED_ENV newlines={raw.count(chr(10))}')
want = {
  'BINANCE_TESTNET': '1',
  'BINANCE_FORCE_TESTNET': '1',
  'BINANCE_FORCE_MAINNET': '0',
  'BINANCE_PAPER': '0',
  'FORWARD_DRY_RUN': '0',
  'SCANNER_EXEC': '1',
}
lines = raw.splitlines()
out, seen = [], set()
for line in lines:
    if '=' in line and not line.strip().startswith('#'):
        k = line.split('=', 1)[0].strip()
        if k in want:
            out.append(f'{k}={want[k]}')
            seen.add(k)
            continue
    out.append(line)
for k, v in want.items():
    if k not in seen:
        out.append(f'{k}={v}')
Path('/etc/bilshenz.env.pre-testnet').write_text(raw, encoding='utf-8')
p.write_text('\n'.join(out) + '\n', encoding='utf-8')
p.chmod(0o600)
print('ENV_TESTNET_OK')
for k in sorted(want):
    print(f'{k}={want[k]}')

# Keep locked $100 partition; clear emergency halt
risk = Path('/var/lib/bilshenz/scanner-risk.json')
if risk.exists():
    try:
        raw_r = json.loads(risk.read_text() or '{}')
    except Exception:
        raw_r = {}
    if not isinstance(raw_r, dict):
        raw_r = {}
    raw_r['partition_usd'] = 100.0
    raw_r['exec_halted'] = False
    risk.write_text(json.dumps(raw_r, indent=2) + '\n')
    print('RISK partition=100 exec_halted=False')
PY

# Drop mainnet session so bridge re-auths on testnet (keys via env or phone login).
rm -f /var/lib/bilshenz/binance-session.json \
      /opt/bilshenz/binance_trading_system/python/.binance_session.json 2>/dev/null || true

systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 8
systemctl is-active bilshenz-binance-api bilshenz-forward-bot

''' + PY + r''' -c "
import json, time, urllib.request
final=None
for i in range(25):
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
    sc=h.get('scanner') or {}
    print(i, 'mode', h.get('mode'), 'connected', h.get('connected'),
          'can', sc.get('can_execute'), 'block', sc.get('exec_block'),
          'halted', sc.get('user_exec_halted'), 'part', sc.get('partition_usd'),
          'auth', (sc.get('api_auth') or {}),
          'user_ws', (h.get('user_data_stream') or {}).get('ws_connected'),
          'tick', (h.get('tick_stream') or {}).get('ws_connected'))
    final=h
    if str(h.get('mode','')).lower() in ('testnet','demo') and h.get('connected'):
        print('TESTNET_CONNECTED')
        break
    time.sleep(1)
else:
    print('WAIT_DONE_NOT_CONNECTED')
"
grep -E '^(BINANCE_TESTNET|BINANCE_FORCE_TESTNET|BINANCE_FORCE_MAINNET|SCANNER_EXEC|FORWARD_DRY_RUN)=' /etc/bilshenz.env
# show whether env still has API key placeholders (lengths only)
python3 - <<'PY'
from pathlib import Path
for ln in Path('/etc/bilshenz.env').read_text().splitlines():
    if ln.startswith('BINANCE_API_KEY=') or ln.startswith('BINANCE_API_SECRET='):
        k,v=ln.split('=',1)
        v=v.strip().strip('"').strip("'")
        print(k, 'len', len(v), 'set', bool(v))
print('session_exists', Path('/var/lib/bilshenz/binance-session.json').exists())
PY
curl -sS -o /dev/null -w 'testnet_ping=%{http_code}\n' --max-time 10 https://testnet.binancefuture.com/fapi/v1/ping || true
'''


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=120)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print(err.encode("ascii", "replace").decode("ascii")[-2000:])
    c.close()


if __name__ == "__main__":
    main()
