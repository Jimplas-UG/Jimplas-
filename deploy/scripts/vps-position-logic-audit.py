#!/usr/bin/env python3
"""Live position vs short-first logic audit."""
from __future__ import annotations

import json
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
set -a; . /etc/bilshenz.env; set +a
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions > /tmp/pos.json
curl -sS -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/scanner/snapshot' > /tmp/snap.json
python3 <<'PY'
import json
from collections import defaultdict
h=json.load(open('/tmp/h.json'))
pos=json.load(open('/tmp/pos.json'))
snap=json.load(open('/tmp/snap.json'))
s=h.get('scanner') or {}
print('connected', h.get('connected'), 'mode', h.get('mode'))
print('scanner', {k:s.get(k) for k in ('can_execute','exec_block','active_symbol','pending_count','best_pending','watchlist','risk_locked')})
print('pair', h.get('pair_isolation'))
positions=[p for p in (pos.get('positions') or []) if abs(float(p.get('volume') or p.get('positionAmt') or 0))>0]
print('=== OPEN POSITIONS', len(positions), '===')
by=defaultdict(list)
for p in positions:
  sym=(p.get('symbol') or '').upper()
  amt=float(p.get('volume') or p.get('positionAmt') or 0)
  side=(p.get('positionSide') or p.get('type') or '').upper()
  if not side:
    side='SHORT' if amt<0 else 'LONG'
  entry=p.get('price_open') or p.get('entryPrice') or p.get('entry')
  mark=p.get('price_current') or p.get('markPrice') or p.get('price')
  upnl=p.get('unrealizedPnl') or p.get('unRealizedProfit')
  print({'symbol':sym,'side':side,'amt':amt,'entry':entry,'mark':mark,'upnl':upnl,'leverage':p.get('leverage'),'raw_keys':sorted(p.keys())[:20]})
  by[sym].append({'side':side,'amt':amt,'entry':float(entry or 0),'mark':float(mark or 0),'upnl':float(upnl or 0)})

rows={ (r.get('symbol') or '').upper(): r for r in (snap.get('rows') or []) }
print('=== STRATEGY CHECK ===')
issues=[]
for sym, legs in by.items():
  shorts=[x for x in legs if 'SHORT' in x['side'] or x['amt']<0]
  longs=[x for x in legs if 'LONG' in x['side'] or x['amt']>0]
  row=rows.get(sym) or {}
  print('symbol', sym, 'shorts', len(shorts), 'longs', len(longs), 'scanner_status', row.get('status'), 'pct15m', row.get('pct15m'))
  if longs and not shorts:
    issues.append(f'{sym}: ORPHAN LONG(s) without short — violates short-first')
  if len(shorts)>1:
    issues.append(f'{sym}: multiple shorts stacked')
  if shorts and longs:
    se=shorts[0]['entry']; sm=shorts[0]['mark'] or se
    if se>0:
      adverse=((sm-se)/se)*100.0
      print('  adverse_from_short_pct', round(adverse,3))
      if adverse < 1.5 and len(longs)>=1:
        issues.append(f'{sym}: long open but adverse only {adverse:.2f}% (Long1 needs ~2%)')
      if adverse < 3.5 and len(longs)>=2:
        issues.append(f'{sym}: Long2 open but adverse only {adverse:.2f}% (needs ~4%)')
  if shorts and row.get('status') in (None,'Scanning','Watching','Pending','Closed'):
    issues.append(f'{sym}: exchange short but scanner status={row.get("status")} — adopt/amnesia risk')
if not by:
  print('flat — no live positions to validate')
print('=== ISSUES ===')
for i in issues: print('!', i)
if not issues: print('none')
print('=== ACTIVE SCANNER ROWS ===')
for r in (snap.get('rows') or []):
  if str(r.get('status')) not in ('Scanning','Closed'):
    print({k:r.get(k) for k in ('symbol','status','pct15m','pctGain','retracePct','price','highestPrice','unrealizedPnl','direction')})
print('scanner_block', snap.get('blocks'))
print('exec_events', (s.get('execution_events') or snap.get('execution_events') or [])[:8])
PY
echo === LOG ===
grep -E 'SHORT|Long 1|Long 2|adopt|orphan|coher|reconcile|flatten|PENDING| demote' /var/log/bilshenz/app.log 2>/dev/null | tail -n 60
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
