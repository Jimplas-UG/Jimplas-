#!/usr/bin/env python3
"""Activate live trading on FRA: SCANNER_EXEC=1, FORWARD_DRY_RUN=0, clear exec_halted."""
from __future__ import annotations

from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"

CMD = r'''
set -e
python3 <<'PY'
from pathlib import Path
import json
p = Path('/etc/bilshenz.env')
raw = p.read_text(encoding='utf-8')
if raw.count('\n') < 10 or raw.count('\\n') > 5:
    raise SystemExit(f'REFUSE_SMASHED_ENV newlines={raw.count(chr(10))} literal_bs_n={raw.count(chr(92)+"n")}')
lines = raw.splitlines()
out = []
seen_exec = seen_dry = False
for ln in lines:
    if ln.startswith('SCANNER_EXEC='):
        out.append('SCANNER_EXEC=1'); seen_exec = True
    elif ln.startswith('FORWARD_DRY_RUN='):
        out.append('FORWARD_DRY_RUN=0'); seen_dry = True
    else:
        out.append(ln)
if not seen_exec:
    out.append('SCANNER_EXEC=1')
if not seen_dry:
    out.append('FORWARD_DRY_RUN=0')
Path('/etc/bilshenz.env.pre-rearm').write_text(raw, encoding='utf-8')
p.write_text('\n'.join(out) + '\n', encoding='utf-8')
print('REARMED_ENV SCANNER_EXEC=1 FORWARD_DRY_RUN=0')

risk = Path('/var/lib/bilshenz/scanner-risk.json')
if risk.exists():
    try:
        raw_r = json.loads(risk.read_text() or '{}')
    except Exception:
        raw_r = {}
    if not isinstance(raw_r, dict):
        raw_r = {}
    raw_r['exec_halted'] = False
    # keep locked partition
    raw_r['partition_usd'] = 100.0
    risk.write_text(json.dumps(raw_r, indent=2) + '\n')
    print('CLEARED_EXEC_HALTED partition', raw_r.get('partition_usd'))
else:
    print('NO_RISK_FILE')
PY

systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 6
systemctl is-active bilshenz-binance-api bilshenz-forward-bot

''' + PY + r''' -c "
import json, time, urllib.request
for i in range(20):
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
    sc=h.get('scanner') or {}
    print(i, 'connected', h.get('connected'), 'mode', h.get('mode'),
          'can', sc.get('can_execute'), 'block', sc.get('exec_block'),
          'exec', sc.get('exec_enabled'), 'halted', sc.get('user_exec_halted'),
          'auth', (sc.get('api_auth') or {}).get('signed_ready'),
          'part', sc.get('partition_usd'),
          'user_ws', (h.get('user_data_stream') or {}).get('ws_connected'))
    if h.get('connected') and sc.get('can_execute') is True and not sc.get('user_exec_halted'):
        print('LIVE_ARMED')
        break
    time.sleep(1)
else:
    print('NOT_FULLY_ARMED')
"
grep -E '^(SCANNER_EXEC|FORWARD_DRY_RUN|BINANCE_FORCE_MAINNET|BINANCE_TESTNET)=' /etc/bilshenz.env
'''


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=100)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print(err.encode("ascii", "replace").decode("ascii")[-2000:])
    c.close()


if __name__ == "__main__":
    main()
