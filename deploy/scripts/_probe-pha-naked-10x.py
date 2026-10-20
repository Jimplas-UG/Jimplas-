#!/usr/bin/env python3
"""Why PHAUSDT naked short is exchange 10x — Sep lock breach."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
export PYTHONIOENCODING=utf-8
PY=/opt/bilshenz/binance_trading_system/python/.venv/bin/python
cd /opt/bilshenz/binance_trading_system/python
$PY - <<'PY'
import json, time, urllib.request, re, inspect
from collections import defaultdict

tok = open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
H = {'Authorization': 'Bearer ' + tok}

def get(path):
    req = urllib.request.Request('http://127.0.0.1:8766' + path, headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=20).read())

pos = get('/api/positions')
opens = [p for p in (pos.get('positions') or []) if abs(float(p.get('volume') or 0)) > 1e-12]
print('OPENS', json.dumps(opens, indent=2)[:2000])

import leverage_policy as lp
import momentum_scanner as ms
print('policy naked', lp.symbol_exchange_leverage(has_recovery_long=False))
print('policy hedged', lp.symbol_exchange_leverage(has_recovery_long=True))
src = inspect.getsource(ms.MomentumScanner._manage_positions)
print('manage_uses_symbol_exchange_leverage', 'symbol_exchange_leverage' in src)
print('forbidden_target_LONG1', 'target = LONG1_LEVERAGE' in src)

# log for PHA since open
since = '2026-10-20T00:00'
hits = []
with open('/var/log/bilshenz/binance-api.log', errors='replace') as fh:
    for l in fh:
        if 'PHAUSDT' in l and l.startswith('2026-') and l[:16] >= since[:16]:
            if any(x in l for x in ('SHORT', 'LONG', 'leverage', 'EXEC', 'ensure', 'INVALIDATION', 'RESCUE',
                                   'close', '10x', '5x', 'adverse', 'prepare', 'margin')):
                hits.append(l.strip()[:240])
print('PHA_LOG_N', len(hits))
for l in hits[-40:]:
    print(' ', l)

# AIN episode today (had LONG1)
hits2 = []
with open('/var/log/bilshenz/binance-api.log', errors='replace') as fh:
    for l in fh:
        if 'AINUSDT' in l and l.startswith('2026-10-20'):
            if any(x in l for x in ('SHORT', 'LONG', 'EXEC', 'INVALIDATION', 'RESCUE', 'close', 'leverage', 'pnl')):
                hits2.append(l.strip()[:240])
print('AIN_LOG_N', len(hits2))
for l in hits2[-25:]:
    print(' ', l)

# BRUSDT worst
hits3=[]
with open('/var/log/bilshenz/binance-api.log', errors='replace') as fh:
    for l in fh:
        if 'BRUSDT' in l and l.startswith('2026-10-1'):
            if any(x in l for x in ('SHORT', 'LONG', 'EXEC', 'INVALIDATION', 'RESCUE', 'close', 'PAIR')):
                hits3.append(l.strip()[:240])
print('BR_LOG_N', len(hits3))
for l in hits3[-20:]:
    print(' ', l)

# calendar today detail via deals
import pathlib, calendar
raw=json.loads(pathlib.Path('/var/lib/bilshenz/trade-history-cache.json').read_text())
cut=calendar.timegm(time.strptime('2026-10-20','%Y-%m-%d'))*1000
def ts(d):
    v=float(d.get('time') or 0); return int(v if v>1e12 else v*1000)
today=[d for d in (raw.get('deals') or []) if ts(d)>=cut]
print('TODAY_DEALS', len(today))
for d in sorted(today, key=ts):
    print(time.strftime('%H:%M', time.gmtime(ts(d)/1000)), d.get('symbol'), d.get('type'), d.get('position_side'),
          'qty', d.get('volume') or d.get('qty'), 'px', d.get('price'), 'pnl', d.get('realized_pnl') or d.get('profit'),
          'close', d.get('is_close'), 'quote', round(float(d.get('quote_qty') or 0),2))
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    print(o.read().decode('utf-8', 'replace'))
    err = e.read().decode('utf-8', 'replace')
    if err.strip():
        print('STDERR', err[-1500:])
    c.close()

if __name__ == '__main__':
    main()
