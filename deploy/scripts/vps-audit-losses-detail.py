#!/usr/bin/env python3
"""Deeper loss breakdown Sep 29-30 — read-only."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set +e
TOKEN=$(python3 -c "from pathlib import Path; d={};
[d.__setitem__(a,b.strip().strip(chr(34)).strip(chr(39))) for a,b in (l.split('=',1) for l in Path('/etc/bilshenz.env').read_text().splitlines() if '=' in l and not l.startswith('#'))];
print(d.get('BRIDGE_TOKEN',''))")

# discover close/history routes
python3 - <<'PY'
import os
# grep main routes quickly
import re
from pathlib import Path
src=Path('/opt/bilshenz/binance_trading_system/python/main.py').read_text(errors='replace')
for m in re.finditer(r'@app\.(get|post)\("([^"]+)"', src):
  path=m.group(2)
  if any(k in path for k in ('deal','hist','income','calendar','position','account','status')):
    print(m.group(1).upper(), path)
PY

echo '=== STATUS ACCOUNT ==='
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/status > /tmp/st.json
python3 - <<'PY'
import json
d=json.load(open('/tmp/st.json'))
print({k:d.get(k) for k in ('ok','connected','mode','testnet','balance','equity','profit','can_trade','error','message') if k in d or True})
# print nested
for k in ('account','wallet','balance','equity'):
  if k in d: print('nested', k, d[k])
print('st_keys', list(d.keys())[:30])
PY

echo '=== CALENDAR DETAIL TODAY ==='
curl -sS --max-time 15 -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/trade-calendar?days=3' > /tmp/cal.json
python3 - <<'PY'
import json
d=json.load(open('/tmp/cal.json'))
print('total', d.get('total_pnl'))
for row in d.get('days') or []:
  print(row)
PY

# income endpoint if any
for u in '/api/income?limit=100' '/api/binance/income' '/api/pnl' '/api/realized'; do
  code=$(curl -sS -o /tmp/inc.json -w '%{http_code}' --max-time 10 -H "X-Bridge-Token: $TOKEN" "http://127.0.0.1:8766$u")
  echo "inc $u -> $code"
  if [ "$code" = "200" ]; then python3 -c "import json;d=json.load(open('/tmp/inc.json'));print(type(d), list(d)[:20] if isinstance(d,dict) else len(d))"; break; fi
done

echo '=== LOG CLOSES WITH SYMBOLS Sep29-30 ==='
grep -E '2026-09-29|2026-09-30' /var/log/bilshenz/binance-api.log | grep -E 'scanner closed |SHORT_TP|PULLBACK|INVALIDATION|RESCUE|MANUAL_|EXEC_OK coin=' | grep -v partition | tail -n 80

echo '=== TRADE CACHE ==='
ls -lah /var/lib/bilshenz/trade-history-cache.json 2>/dev/null
python3 - <<'PY'
import json
from pathlib import Path
from collections import defaultdict
import datetime
p=Path('/var/lib/bilshenz/trade-history-cache.json')
if not p.exists():
  print('no cache'); raise SystemExit
d=json.loads(p.read_text())
rows=d if isinstance(d,list) else d.get('deals') or d.get('rows') or d.get('history') or []
print('cache_type', type(d).__name__, 'rows', len(rows) if isinstance(rows,list) else type(rows))
if isinstance(d, dict):
  print('cache_keys', list(d.keys())[:20])
if not isinstance(rows, list):
  raise SystemExit
start=datetime.datetime(2026,9,29,tzinfo=datetime.timezone.utc).timestamp()*1000
events=[]
for r in rows:
  if not isinstance(r, dict): continue
  pnl=r.get('profit', r.get('realized_pnl', r.get('realizedPnl')))
  try: pnl=float(pnl)
  except: continue
  t=r.get('time') or r.get('ts') or 0
  try: t=int(t)
  except: t=0
  if t and t<1e12: t*=1000
  if t and t < start: continue
  events.append((t, r.get('symbol'), r.get('type'), pnl, bool(r.get('is_close')), r.get('position_side')))
events.sort()
print('events_since_29', len(events))
# only closes if flagged else all with pnl
closes=[e for e in events if e[4] or abs(e[3])>0]
sum_pnl=sum(e[3] for e in closes)
print('sum', round(sum_pnl,2))
by_day=defaultdict(float)
for t,sym,typ,pnl,ic,ps in closes:
  day=datetime.datetime.fromtimestamp(t/1000, datetime.timezone.utc).strftime('%Y-%m-%d') if t else '?'
  by_day[day]+=pnl
print('by_day', {k:round(v,2) for k,v in sorted(by_day.items())})
print('LAST20')
for e in closes[-20:]:
  t,sym,typ,pnl,ic,ps=e
  ts=datetime.datetime.fromtimestamp(t/1000, datetime.timezone.utc).isoformat() if t else '?'
  print(ts, sym, typ, ps, round(pnl,2), 'close' if ic else 'fill')
worst=sorted(closes, key=lambda x: x[3])[:15]
print('WORST')
for e in worst:
  t,sym,typ,pnl,ic,ps=e
  ts=datetime.datetime.fromtimestamp(t/1000, datetime.timezone.utc).isoformat() if t else '?'
  print(ts, sym, typ, round(pnl,2))
PY
"""

def main():
    pkey=paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username='root', pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
    _,o,e=c.exec_command(CMD, timeout=120)
    print(o.read().decode('utf-8','replace'))
    err=e.read().decode('utf-8','replace')
    if err.strip(): print('STDERR', err[-800:])
    c.close()
if __name__=='__main__':
    main()
