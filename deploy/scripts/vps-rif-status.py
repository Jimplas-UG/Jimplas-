#!/usr/bin/env python3
"""Live status for current RIFUSDT short trade."""
from __future__ import annotations

import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
SYMBOL = os.environ.get("CHECK_SYMBOL", "RIFUSDT").upper()

CMD = r"""
set -a; . /etc/bilshenz.env; set +a
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
SYM='__SYM__'
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json
curl -sS -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/positions' > /tmp/pos.json || echo '{}' >/tmp/pos.json
curl -sS -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/scanner/snapshot' > /tmp/snap.json || echo '{}' >/tmp/snap.json
curl -sS -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/logs?limit=80' > /tmp/logs.json || echo '{}' >/tmp/logs.json
python3 - <<PY
import json
SYM='$SYM'
h=json.load(open('/tmp/h.json'))
s=h.get('scanner') or {}
pos=(json.load(open('/tmp/pos.json')).get('positions') or [])
rows={str(r.get('symbol') or '').upper(): r for r in (json.load(open('/tmp/snap.json')).get('rows') or [])}
deals=json.load(open('/tmp/logs.json')).get('deals') or []
print('mode', h.get('mode'), 'connected', h.get('connected'), 'can_execute', s.get('can_execute'))
print('active_symbol', s.get('active_symbol'), 'risk_locked', s.get('risk_locked'))
print('partitions', s.get('short_partition_pct'), s.get('long1_partition_pct'), s.get('long2_partition_pct'))
print('tp/pullback short_tp', s.get('short_tp_pct'), 'long_tp', s.get('long_tp_pct'), 'long_hedge_pb', s.get('long_pullback_pct'))
print()
legs=[]
for p in pos:
  if str(p.get('symbol') or '').upper()!=SYM: continue
  if float(p.get('volume') or 0)<=0: continue
  legs.append(p)
  print('POS', p.get('positionSide') or p.get('type') or p.get('side'),
        'vol', p.get('volume'), 'entry', p.get('price_open') or p.get('entryPrice'),
        'mark', p.get('markPrice') or p.get('mark'),
        'pnl', p.get('profit') or p.get('unRealizedProfit'),
        'lev', p.get('leverage'))
if not legs:
  print('POS none open for', SYM)
r=rows.get(SYM) or {}
print('SCANNER_ROW', {k:r.get(k) for k in ('status','price','pct15m','pctGain','retracePct','qualifyingPct','timeframe')})
# compute adverse vs short entry
short=[p for p in legs if str(p.get('positionSide') or p.get('type') or p.get('side') or '').upper() in ('SHORT','SELL')]
long=[p for p in legs if str(p.get('positionSide') or p.get('type') or p.get('side') or '').upper() in ('LONG','BUY')]
if short:
  entry=float(short[0].get('price_open') or short[0].get('entryPrice') or 0)
  px=float(r.get('price') or short[0].get('markPrice') or short[0].get('mark') or entry or 0)
  if entry>0 and px>0:
    adverse=((px-entry)/entry)*100
    favor=((entry-px)/entry)*100
    tp=entry*(1-float(s.get('short_tp_pct') or 2.5)/100)
    l1=entry*1.02
    l2=entry*1.04
    print()
    print('ENTRY', entry, 'LIVE', px)
    print('adverse_pct(+ means against short)', round(adverse,3))
    print('favor_pct(+ means short winning)', round(favor,3))
    print('SHORT_TP_price', round(tp,6), 'distance_to_tp_pct', round(((px-tp)/entry)*100 if px>tp else 0,3) if px>tp else 'AT_OR_PAST_TP')
    print('Long1_trigger(+2%)', round(l1,6), 'need_more_pct', round(max(0,2.0-adverse),3))
    print('Long2_trigger(+4%)', round(l2,6), 'need_more_pct', round(max(0,4.0-adverse),3))
    print('long_legs_open', len(long))
print()
print('RECENT_DEALS', SYM)
for d in deals:
  if str(d.get('symbol') or '').upper()!=SYM: continue
  print(d.get('time'), 'CLOSE' if d.get('is_close') else 'OPEN', d.get('position_side'), 'vol', d.get('volume'), 'px', d.get('price'), 'pnl', d.get('profit'))
PY
grep -E "RIFUSDT|scanner SHORT RIF|LONG1|LONG2|SHORT_TP|SMART_EXIT|PULLBACK|adopted" /var/log/bilshenz/app.log 2>/dev/null | tail -n 40
""".replace("__SYM__", SYMBOL)


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err[-1500:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
