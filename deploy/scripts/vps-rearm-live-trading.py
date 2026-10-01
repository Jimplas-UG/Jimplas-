#!/usr/bin/env python3
"""Re-arm live trading on FRA: SCANNER_EXEC=1 FORWARD_DRY_RUN=0 (no strategy changes)."""
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
p = Path('/etc/bilshenz.env')
raw = p.read_text(encoding='utf-8')
# safety: refuse if smashed into one line / literal backslash-n soup
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
text = '\n'.join(out) + '\n'
# backup then write
Path('/etc/bilshenz.env.pre-rearm').write_text(raw, encoding='utf-8')
p.write_text(text, encoding='utf-8')
print('REARMED')
for ln in text.splitlines():
    if ln.startswith('SCANNER_EXEC=') or ln.startswith('FORWARD_DRY_RUN=') or ln.startswith('BINANCE_FORCE_MAINNET=') or ln.startswith('BINANCE_TESTNET='):
        print(ln)
    if ln.startswith('BRIDGE_TOKEN=') or ln.startswith('SESSION_ENC_KEY=') or ln.startswith('BINANCE_API_KEY='):
        k,v = ln.split('=',1)
        print(f'{k} len={len(v.strip().strip(chr(34)).strip(chr(39)))}')
print('lines', len(out), 'newlines', text.count(chr(10)))
PY

# Restart API so env halt flags are picked up (scanner reads os.environ at order time too,
# but some paths cache at process start).
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 6
systemctl is-active bilshenz-binance-api bilshenz-forward-bot

TOK=$(grep '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS -m 6 http://127.0.0.1:8766/health > /tmp/h.json
''' + PY + r''' -c "
import json, time, urllib.request, os
h=json.load(open('/tmp/h.json'))
# wait briefly for session restore
for i in range(15):
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
    sc=h.get('scanner') or {}
    print(i, 'connected', h.get('connected'), 'can', sc.get('can_execute'), 'block', sc.get('exec_block'), 'exec', sc.get('exec_enabled'),
          'user', (h.get('user_data_stream') or {}).get('ws_connected'))
    if h.get('connected') and sc.get('can_execute') is True:
        print('LIVE_ARMED')
        break
    time.sleep(1)
else:
    sc=h.get('scanner') or {}
    print('FINAL', 'connected', h.get('connected'), 'can', sc.get('can_execute'), 'block', sc.get('exec_block'))
"
grep -E '^(SCANNER_EXEC|FORWARD_DRY_RUN|BINANCE_FORCE_MAINNET|BINANCE_TESTNET)=' /etc/bilshenz.env
'''

def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print(err.encode("ascii", "replace").decode("ascii")[-2000:])
    c.close()

if __name__ == "__main__":
    main()
