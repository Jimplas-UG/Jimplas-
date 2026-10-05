#!/usr/bin/env python3
"""Audit recent closed PnL / losses since restart — read-only, no strategy changes."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set +e
TOKEN=$(python3 -c "from pathlib import Path; d={};
[d.__setitem__(a,b.strip().strip(chr(34)).strip(chr(39))) for a,b in (l.split('=',1) for l in Path('/etc/bilshenz.env').read_text().splitlines() if '=' in l and not l.startswith('#'))];
print(d.get('BRIDGE_TOKEN',''))")
DESK=$(python3 -c "from pathlib import Path; d={};
[d.__setitem__(a,b.strip().strip(chr(34)).strip(chr(39))) for a,b in (l.split('=',1) for l in Path('/etc/bilshenz.env').read_text().splitlines() if '=' in l and not l.startswith('#'))];
print(d.get('DESK_API_KEY',''))")

echo '=== MODE / ACCOUNT ==='
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json
python3 - <<'PY'
import json
h=json.load(open('/tmp/h.json'))
s=h.get('scanner') or {}
print('mode', h.get('mode'), 'connected', h.get('connected'), 'testnet', h.get('testnet'))
print('strategy', s.get('strategy_id'), 'partition', s.get('partition_usd'))
print('balance', h.get('balance') or h.get('equity') or (h.get('account') or {}).get('balance'))
acct=h.get('account') or {}
for k in ('balance','equity','available','margin','profit','unrealized'):
  if k in acct or k in h: print(k, acct.get(k, h.get(k)))
print('keys', sorted(h.keys())[:40])
PY

echo '=== POSITIONS NOW ==='
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions > /tmp/pos.json 2>/dev/null || curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/binance/positions' > /tmp/pos.json
python3 - <<'PY'
import json
from pathlib import Path
p=Path('/tmp/pos.json')
if not p.exists() or not p.read_text().strip():
  print('no positions endpoint body')
else:
  try:
    d=json.loads(p.read_text())
  except Exception as e:
    print('parse_err', e, p.read_text()[:200]); raise SystemExit
  rows=d if isinstance(d, list) else d.get('positions') or d.get('rows') or []
  print('open_legs', len(rows))
  tot=0
  for r in rows:
    pnl=float(r.get('profit') or r.get('unRealizedProfit') or r.get('unrealized') or 0)
    tot+=pnl
    print(r.get('symbol'), r.get('positionSide') or r.get('side') or r.get('type'), 'qty', r.get('volume') or r.get('positionAmt'), 'entry', r.get('price_open') or r.get('entryPrice'), 'pnl', round(pnl,2))
  print('floating_sum', round(tot,2))
PY

echo '=== TRADE HISTORY / DEALS ==='
for u in '/api/deals?limit=80' '/api/history?limit=80' '/api/trade-history?limit=80' '/api/binance/deals?limit=80'; do
  code=$(curl -sS -o /tmp/deals.json -w '%{http_code}' --max-time 12 -H "X-Bridge-Token: $TOKEN" "http://127.0.0.1:8766$u")
  echo "try $u -> $code"
  if [ "$code" = "200" ]; then break; fi
done
python3 - <<'PY'
import json, datetime
from collections import defaultdict
from pathlib import Path
raw=Path('/tmp/deals.json').read_text(errors='replace') if Path('/tmp/deals.json').exists() else ''
try:
  d=json.loads(raw) if raw.strip() else {}
except Exception as e:
  print('deals_parse', e, raw[:300]); d={}
rows=d if isinstance(d, list) else d.get('deals') or d.get('history') or d.get('rows') or d.get('fills') or []
print('deal_rows', len(rows), 'top_keys', list(d.keys())[:20] if isinstance(d, dict) else 'list')
# normalize
closes=[]
for r in rows:
  if not isinstance(r, dict): continue
  pnl=r.get('profit')
  if pnl is None: pnl=r.get('realized_pnl')
  if pnl is None: pnl=r.get('realizedPnl')
  try: pnl=float(pnl)
  except: continue
  is_close = r.get('is_close') or r.get('isClose') or str(r.get('type','')).upper() in ('BUY','SELL')
  # prefer close-flagged
  if r.get('is_close') is False and r.get('realized_pnl') in (None,0,''):
    continue
  t=r.get('time') or r.get('ts') or r.get('close_time') or 0
  try: t=int(t)
  except: t=0
  if t and t < 1e12: t*=1000
  closes.append({
    't': t,
    'sym': r.get('symbol') or r.get('coin'),
    'type': r.get('type') or r.get('side'),
    'pnl': pnl,
    'is_close': bool(r.get('is_close') or r.get('isClose')),
    'vol': r.get('volume') or r.get('qty'),
    'price': r.get('price') or r.get('fill_price'),
  })
# if few is_close, use all with nonzero pnl
use=[x for x in closes if x['is_close'] or abs(x['pnl'])>1e-9]
use=sorted(use, key=lambda x: x['t'])
print('pnl_events', len(use))
# since Sep 29 00:00 UTC (restart window from chat)
start=datetime.datetime(2026,9,29,0,0,tzinfo=datetime.timezone.utc).timestamp()*1000
win=[x for x in use if x['t']>=start or x['t']==0]
if not any(x['t'] for x in use):
  win=use[-40:]
sum_all=sum(x['pnl'] for x in win)
wins=[x for x in win if x['pnl']>0]
losses=[x for x in win if x['pnl']<0]
print('window_from', '2026-09-29 UTC')
print('n', len(win), 'sum_pnl', round(sum_all,2), 'wins', len(wins), 'losses', len(losses))
print('gross_win', round(sum(x['pnl'] for x in wins),2), 'gross_loss', round(sum(x['pnl'] for x in losses),2))
# worst
worst=sorted(win, key=lambda x: x['pnl'])[:12]
print('WORST12')
for x in worst:
  ts=datetime.datetime.fromtimestamp(x['t']/1000, datetime.timezone.utc).isoformat() if x['t'] else '?'
  print(ts, x['sym'], x['type'], 'pnl', round(x['pnl'],2), 'close?', x['is_close'])
best=sorted(win, key=lambda x: x['pnl'], reverse=True)[:8]
print('BEST8')
for x in best:
  ts=datetime.datetime.fromtimestamp(x['t']/1000, datetime.timezone.utc).isoformat() if x['t'] else '?'
  print(ts, x['sym'], x['type'], 'pnl', round(x['pnl'],2))
# by symbol
by=defaultdict(float)
for x in win: by[x['sym']] += x['pnl']
print('BY_SYMBOL')
for s,v in sorted(by.items(), key=lambda kv: kv[1]):
  print(s, round(v,2))
PY

echo '=== CALENDAR ==='
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/trade-calendar?days=7' > /tmp/cal.json
python3 - <<'PY'
import json
from pathlib import Path
raw=Path('/tmp/cal.json').read_text(errors='replace')
try: d=json.loads(raw)
except Exception as e: print('cal_err', e, raw[:200]); raise SystemExit
days=d.get('days') or []
print('total_pnl', d.get('total_pnl'), 'days', len(days))
for row in days[-10:]:
  print(row.get('date') or row.get('day'), 'pnl', row.get('pnl') or row.get('realized_pnl') or row.get('net'), 'trades', row.get('trades') or row.get('count'))
PY

echo '=== INCOME / CLOSE REASONS FROM LOG ==='
DAY29=2026-09-29
DAY30=2026-09-30
grep -E "$DAY29|$DAY30" /var/log/bilshenz/binance-api.log | grep -E 'scanner closed|SHORT_TP|INVALIDATION|RESCUE|MANUAL_|EXEC_OK|realized|entry cooldown' | tail -n 50
echo '=== CLOSE REASON COUNTS ==='
python3 - <<'PY'
from pathlib import Path
from collections import Counter
import re
text=Path('/var/log/bilshenz/binance-api.log').read_text(errors='replace')
lines=[ln for ln in text.splitlines() if '2026-09-29' in ln or '2026-09-30' in ln]
c=Counter()
for ln in lines:
  m=re.search(r'reason=([A-Z0-9_]+)', ln)
  if m and ('cooldown' in ln or 'closed' in ln):
    c[m.group(1)] += 1
  if 'SHORT_TP' in ln: c['SHORT_TP_mention'] += 1
  if 'MANUAL_SHORT_FLATTEN' in ln: c['MANUAL_SHORT_FLATTEN'] += 1
  if 'PAIR_INVALIDATION' in ln or 'invalidation' in ln.lower(): c['invalidation'] += 1
  if 'RESCUE' in ln or 'hedge_rescue' in ln: c['rescue'] += 1
  if 'scanner SHORT failed' in ln: c['short_failed'] += 1
  if 'scanner SHORT ' in ln and 'qty=' in ln and 'failed' not in ln: c['short_opened'] += 1
print(dict(c))
PY
"""

def main():
    pkey=paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username='root', pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
    _,o,e=c.exec_command(CMD, timeout=120)
    print(o.read().decode('utf-8','replace'))
    err=e.read().decode('utf-8','replace')
    if err.strip(): print('STDERR', err[-1000:])
    c.close()

if __name__=='__main__':
    main()
