#!/usr/bin/env python3
"""Why not pulling trades — read-only FRA probe."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set +e
TOKEN=$(python3 -c "from pathlib import Path; d={};
[d.__setitem__(a,b.strip().strip(chr(34)).strip(chr(39))) for a,b in (l.split('=',1) for l in Path('/etc/bilshenz.env').read_text().splitlines() if '=' in l and not l.startswith('#'))];
print(d.get('BRIDGE_TOKEN',''))")
echo '=== ENV (no secrets) ==='
grep -E '^(BINANCE_TESTNET|BINANCE_FORCE_|BINANCE_PAPER|FORWARD_|SCANNER_)' /etc/bilshenz.env | sed 's/=.*/=***/' 
# show values safely for flags only
python3 - <<'PY'
from pathlib import Path
keys=('BINANCE_TESTNET','BINANCE_FORCE_TESTNET','BINANCE_FORCE_MAINNET','BINANCE_PAPER','FORWARD_DRY_RUN','SCANNER_EXEC','SCANNER_ENABLED')
d={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
  if '=' in l and not l.startswith('#'):
    a,b=l.split('=',1); d[a]=b.strip().strip('"').strip("'")
for k in keys:
  print(f'{k}={d.get(k)}')
print('risk_file', Path('/var/lib/bilshenz/scanner-risk.json').read_text().strip() if Path('/var/lib/bilshenz/scanner-risk.json').exists() else 'missing')
PY

echo '=== HEALTH ==='
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json
python3 - <<'PY'
import json
h=json.load(open('/tmp/h.json'))
s=h.get('scanner') or {}
print('mode', h.get('mode'), 'connected', h.get('connected'))
print('strategy', s.get('strategy_id') or s.get('strategy'))
print('can_execute', s.get('can_execute'), 'exec_enabled', s.get('exec_enabled'), 'block', s.get('exec_block'))
print('halted', s.get('user_exec_halted'), 'partition', s.get('partition_usd'), 'locked', s.get('risk_locked'))
print('active', s.get('active_symbol'), 'pending', s.get('pending_count'), 'watchlist', s.get('watchlist'))
print('last_exec_error', s.get('last_exec_error'))
print('cool', h.get('rest_cool_s') or s.get('rest_cool_s'))
PY

echo '=== SNAPSHOT MOVERS ==='
curl -sS --max-time 15 -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/scanner/snapshot' > /tmp/snap.json
python3 - <<'PY'
import json
from collections import Counter
d=json.load(open('/tmp/snap.json'))
rows=d.get('rows') or []
print('rows', len(rows), 'status', dict(Counter(str(r.get('status')) for r in rows)))
def g(r):
  try: return float(r.get('pctGain') if r.get('pctGain') is not None else r.get('pct15m') or -999)
  except: return -999
top=sorted(rows, key=g, reverse=True)[:10]
print('TOP10')
for r in top:
  print(r.get('symbol'), 'st', r.get('status'), 'gain', g(r), 'pct15m', r.get('pct15m'), 'retrace', r.get('retracePct'))
hot=[r for r in rows if g(r)>=5]
near=[r for r in rows if 3<=g(r)<5]
print('ge5', len(hot), [r.get('symbol') for r in hot])
print('3to5', [(r.get('symbol'), round(g(r),2)) for r in near[:12]])
watching=[r for r in rows if str(r.get('status'))=='Watching']
print('watching', len(watching))
for r in watching[:8]:
  print(' W', r.get('symbol'), 'gain', g(r), 'retrace', r.get('retracePct'), 'pct15m', r.get('pct15m'))
PY

echo '=== RECENT SHORT / FAIL (today) ==='
DAY=$(date -u +%Y-%m-%d)
grep "$DAY" /var/log/bilshenz/binance-api.log 2>/dev/null | grep -E 'scanner SHORT |EXEC_OK|EXEC_FAIL|entry cooldown|can_execute|exec_halt|partition' | tail -n 40
echo '=== COUNTS TODAY ==='
python3 - <<'PY'
from pathlib import Path
from collections import Counter
import datetime
day=datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d')
text=Path('/var/log/bilshenz/binance-api.log').read_text(errors='replace') if Path('/var/log/bilshenz/binance-api.log').exists() else ''
lines=[ln for ln in text.splitlines() if day in ln]
c=Counter()
for ln in lines:
  if 'scanner SHORT ' in ln and 'qty=' in ln and 'failed' not in ln: c['short_opened']+=1
  if 'scanner SHORT failed' in ln: c['short_failed']+=1
  if 'EXEC_FAIL' in ln and 'cooling' in ln: c['fail_cool']+=1
  if 'EXEC_FAIL' in ln and 'cooling' not in ln: c['fail_other']+=1
  if 'EXEC_OK' in ln and 'SELL' in ln: c['exec_ok_sell']+=1
  if 'entry cooldown' in ln: c['cooldown']+=1
print(dict(c), 'log_lines', len(lines))
# last open timestamp
opens=[ln for ln in lines if 'scanner SHORT ' in ln and 'qty=' in ln]
print('last_open', opens[-1] if opens else 'none')
fails=[ln for ln in lines if 'scanner SHORT failed' in ln]
print('last_fail', fails[-1] if fails else 'none')
PY
"""

def main():
    pkey=paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username='root', pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
    _,o,e=c.exec_command(CMD, timeout=90)
    print(o.read().decode('utf-8','replace'))
    err=e.read().decode('utf-8','replace')
    if err.strip(): print('STDERR', err[-800:])
    c.close()

if __name__=='__main__':
    main()
