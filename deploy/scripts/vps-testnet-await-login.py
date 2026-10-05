#!/usr/bin/env python3
"""Clear mainnet keys from env while staying on testnet; stop -2015 spam until app login."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=40, look_for_keys=False, allow_agent=False)
CMD = r'''
set -euo pipefail
python3 <<'PY'
from pathlib import Path
p = Path('/etc/bilshenz.env')
raw = p.read_text(encoding='utf-8')
Path('/etc/bilshenz.env.pre-clear-keys-testnet').write_text(raw, encoding='utf-8')
out = []
for ln in raw.splitlines():
    if ln.startswith('BINANCE_API_KEY='):
        out.append('BINANCE_API_KEY=')
    elif ln.startswith('BINANCE_API_SECRET='):
        out.append('BINANCE_API_SECRET=')
    else:
        out.append(ln)
# ensure testnet flags remain
text = '\n'.join(out) + '\n'
need = {
  'BINANCE_TESTNET': '1',
  'BINANCE_FORCE_TESTNET': '1',
  'BINANCE_FORCE_MAINNET': '0',
  'SCANNER_EXEC': '1',
  'FORWARD_DRY_RUN': '0',
}
lines = text.splitlines()
seen=set(); final=[]
for ln in lines:
    if '=' in ln and not ln.strip().startswith('#'):
        k=ln.split('=',1)[0].strip()
        if k in need:
            final.append(f'{k}={need[k]}'); seen.add(k); continue
    final.append(ln)
for k,v in need.items():
    if k not in seen:
        final.append(f'{k}={v}')
p.write_text('\n'.join(final)+'\n', encoding='utf-8')
p.chmod(0o600)
print('CLEARED_MAINNET_KEYS_ON_TESTNET')
for k in sorted(need):
    print(f'{k}={need[k]}')
PY
rm -f /var/lib/bilshenz/binance-session.json \
      /opt/bilshenz/binance_trading_system/python/.binance_session.json 2>/dev/null || true
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 6
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
python3 - <<'PY'
import json, urllib.request
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
sc=h.get('scanner') or {}
print('mode', h.get('mode'), 'connected', h.get('connected'),
      'can', sc.get('can_execute'), 'block', sc.get('exec_block'),
      'part', sc.get('partition_usd'),
      'tick', (h.get('tick_stream') or {}).get('ws_connected'))
PY
grep -E '^(BINANCE_TESTNET|BINANCE_FORCE_TESTNET|BINANCE_FORCE_MAINNET|SCANNER_EXEC|FORWARD_DRY_RUN|BINANCE_API_KEY|BINANCE_API_SECRET)=' /etc/bilshenz.env | sed 's/BINANCE_API_SECRET=.*/BINANCE_API_SECRET=/; s/BINANCE_API_KEY=.*/BINANCE_API_KEY=/'
'''
_,o,e=c.exec_command(CMD, timeout=90)
print(o.read().decode('utf-8','replace').encode('ascii','replace').decode('ascii'))
err=e.read().decode('utf-8','replace')
if err.strip():
    print(err.encode('ascii','replace').decode('ascii')[-1500:])
c.close()
