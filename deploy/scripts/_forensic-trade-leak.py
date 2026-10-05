#!/usr/bin/env python3
"""Forensic: find leak where live trades violate short_first_v1 / Sep23 criteria."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=40, look_for_keys=False, allow_agent=False)

CMD = r'''
python3 <<'PY'
import json, re, urllib.request
from collections import defaultdict, deque
from pathlib import Path

# --- live state ---
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {}
print('MODE', h.get('mode'), 'conn', h.get('connected'), 'can', sc.get('can_execute'), 'block', sc.get('exec_block'))
print('STRAT', sc.get('strategy_id'), 'part', sc.get('partition_usd'), 'active', sc.get('active_symbol'))
print('KNOBS', {k:sc.get(k) for k in (
 'short_partition_pct','long1_partition_pct','long2_partition_pct','short_tp_pct','long_tp_pct',
 'long_pullback_pct','short_pullback_pct','min_live_entry_pct','max_retrace_entry_pct','entry_timeframe'
)})
print('LAST_ERR', sc.get('last_exec_error'))
print('EVENTS_RECENT')
for e in (sc.get('execution_events') or [])[:25]:
    print(json.dumps({k:e.get(k) for k in ('ts','symbol','leg','side','stage','quantity','fill_price','error')}, default=str)[:320])

# snapshot active rows
tok=None
for ln in Path('/etc/bilshenz.env').read_text().splitlines():
    if ln.startswith('BRIDGE_TOKEN='):
        tok=ln.split('=',1)[1].strip().strip('"').strip("'")
req=urllib.request.Request('http://127.0.0.1:8766/api/scanner/snapshot', headers={'Authorization':'Bearer '+tok})
snap=json.loads(urllib.request.urlopen(req, timeout=12).read())
rows=snap.get('rows') or []
print('ACTIVE_ROWS')
for r in rows:
    st=str(r.get('status') or '')
    if st not in ('Scanning','Closed',''):
        print(r.get('symbol'), st, '15m', r.get('pct15m'), 'gain', r.get('pctGain'), 'retrace', r.get('retracePct'), 'pnl', r.get('unrealizedPnl'))

# positions
req=urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={'Authorization':'Bearer '+tok})
pos=json.loads(urllib.request.urlopen(req, timeout=12).read())
plist=pos.get('positions') or []
print('OPEN_POS', len(plist))
for p in plist:
    print({k:p.get(k) for k in ('symbol','type','positionSide','leg','volume','entryPrice','markPrice','leverage','profit')})

# --- parse log timeline last 12h ---
log=Path('/var/log/bilshenz/binance-api.log').read_text(errors='replace')
# also .1 if needed
try:
    log += Path('/var/log/bilshenz/binance-api.log.1').read_text(errors='replace')
except Exception:
    pass

# Keep Oct 2-3 lines
lines=[ln for ln in log.splitlines() if '2026-10-0' in ln]

violations=[]
# Track per-symbol state machine from logs
state=defaultdict(lambda: {'short':False,'l1':False,'l2':False,'short_entry':None,'events':[]})

rx_short=re.compile(r'(?P<ts>2026-10-\d\dT\S+) .*scanner SHORT (?P<sym>\S+) qty=(?P<qty>\S+) @ (?P<px>\S+)')
rx_l1=re.compile(r'(?P<ts>2026-10-\d\dT\S+) .*scanner LONG1 (?P<sym>\S+) qty=(?P<qty>\S+) @ (?P<px>\S+)')
rx_l2=re.compile(r'(?P<ts>2026-10-\d\dT\S+) .*scanner LONG2 (?P<sym>\S+) qty=(?P<qty>\S+) @ (?P<px>\S+)')
rx_fail=re.compile(r'(?P<ts>2026-10-\d\dT\S+) .*scanner (?P<leg>SHORT|LONG1|LONG2) failed (?P<sym>\S+): (?P<err>.+?)(?:\s+latency|$)')
rx_close_leg=re.compile(r'(?P<ts>2026-10-\d\dT\S+) .*scanner closed leg (?P<sym>\S+) (?P<leg>\S+) reason=(?P<reason>\S+)')
rx_close=re.compile(r'(?P<ts>2026-10-\d\dT\S+) .*scanner closed (?P<sym>\S+) reason=(?P<reason>\S+)')
rx_inv=re.compile(r'(?P<ts>2026-10-\d\dT\S+) .*scanner (?P<sym>\S+) INVALIDATION adverse=(?P<adv>[\d.]+)')
rx_pb=re.compile(r'(?P<ts>2026-10-\d\dT\S+) .*scanner (?P<sym>\S+) (?P<kind>LONG1_PULLBACK|LONG2_PULLBACK|SHORT_PULLBACK) (?P<pct>[\d.]+)% \(.*price=(?P<px>\S+).*entry=(?P<entry>\S+)')
rx_adopt=re.compile(r'(?P<ts>2026-10-\d\dT\S+) .*scanner adopted exchange (?P<leg>SHORT|LONG1|LONG2) (?P<sym>\S+)')
rx_exec_ok=re.compile(r'(?P<ts>2026-10-\d\dT\S+) .*EXEC_OK coin=(?P<sym>\S+) side=(?P<side>\S+) qty=(?P<qty>\S+) fill=(?P<fill>\S+).*')
# also look for wrong-side primary
rx_try=re.compile(r'(?P<ts>2026-10-\d\dT\S+) .*scanner (?P<msg>.*)')

seq=[]
for ln in lines:
    m=rx_short.search(ln)
    if m:
        sym=m.group('sym'); st=state[sym]; st['short']=True; st['short_entry']=float(m.group('px'))
        seq.append(('SHORT_OK', m.group('ts'), sym, float(m.group('px')), float(m.group('qty')))); continue
    m=rx_l1.search(ln)
    if m:
        sym=m.group('sym'); st=state[sym]
        px=float(m.group('px'))
        # LEAK: Long1 without short
        if not st['short']:
            violations.append(('LONG1_WITHOUT_SHORT', m.group('ts'), sym, px))
        # LEAK: Long1 before +2% adverse from short entry
        if st['short_entry']:
            adv=(px/st['short_entry']-1)*100
            if adv < 1.8:  # allow tiny fill slip under 2.0
                violations.append(('LONG1_EARLY_ADVERSE', m.group('ts'), sym, f'adv={adv:.2f}% entry={st["short_entry"]} fill={px}'))
        st['l1']=True
        seq.append(('LONG1_OK', m.group('ts'), sym, px)); continue
    m=rx_l2.search(ln)
    if m:
        sym=m.group('sym'); st=state[sym]
        px=float(m.group('px'))
        if not st['short']:
            violations.append(('LONG2_WITHOUT_SHORT', m.group('ts'), sym, px))
        if st['short_entry']:
            adv=(px/st['short_entry']-1)*100
            if adv < 3.6:
                violations.append(('LONG2_EARLY_ADVERSE', m.group('ts'), sym, f'adv={adv:.2f}% entry={st["short_entry"]} fill={px}'))
        # Long2 without Long1 ever (unless long1_was_closed path — hard to see; flag if never L1_OK and never L1 fail after short)
        if not st['l1']:
            violations.append(('LONG2_WITHOUT_LONG1_OPEN', m.group('ts'), sym, f'adv_vs_short={(px/st["short_entry"]-1)*100 if st["short_entry"] else "?"}'))
        st['l2']=True
        seq.append(('LONG2_OK', m.group('ts'), sym, px)); continue
    m=rx_close_leg.search(ln)
    if m:
        sym=m.group('sym'); leg=m.group('leg'); reason=m.group('reason')
        if leg=='long1': state[sym]['l1']=False
        if leg=='long2': state[sym]['l2']=False
        seq.append(('CLOSE_LEG', m.group('ts'), sym, leg, reason)); continue
    m=rx_close.search(ln)
    if m:
        sym=m.group('sym'); reason=m.group('reason')
        # reset
        state[sym]={'short':False,'l1':False,'l2':False,'short_entry':None,'events':[]}
        seq.append(('CLOSE_ALL', m.group('ts'), sym, reason)); continue
    m=rx_inv.search(ln)
    if m:
        seq.append(('INV', m.group('ts'), m.group('sym'), float(m.group('adv'))))
        continue
    m=rx_pb.search(ln)
    if m:
        kind=m.group('kind'); sym=m.group('sym'); px=float(m.group('px')); entry=float(m.group('entry'))
        st=state[sym]
        # LEAK: long pullback while short still underwater (price >= short entry)
        if kind.startswith('LONG') and st['short_entry'] and px >= st['short_entry'] - 1e-12:
            violations.append(('LONG_PULLBACK_WHILE_SHORT_UNDERWATER', m.group('ts'), sym, kind, f'px={px} short_entry={st["short_entry"]}'))
        seq.append(('PB', m.group('ts'), sym, kind, float(m.group('pct')), px, entry)); continue
    m=rx_adopt.search(ln)
    if m:
        seq.append(('ADOPT', m.group('ts'), m.group('sym'), m.group('leg'))); continue
    m=rx_fail.search(ln)
    if m:
        seq.append(('FAIL', m.group('ts'), m.group('sym'), m.group('leg'), m.group('err')[:80])); continue

print('\n=== LAST 60 TRADE EVENTS ===')
for e in seq[-60:]:
    print(e)

print('\n=== VIOLATIONS / LEAKS ===')
if not violations:
    print('NONE_IN_PARSER')
else:
    for v in violations[-40:]:
        print(v)

# Count patterns
from collections import Counter
c=Counter(v[0] for v in violations)
print('VIOLATION_COUNTS', dict(c))

# Wrong-way: EXEC_OK BUY as SHORT or SELL as LONG1?
print('\n=== EXEC SIDE vs LEG (from events API + log) ===')
# From health events
for e in (sc.get('execution_events') or [])[:40]:
    leg=(e.get('leg') or '').upper(); side=(e.get('side') or '').upper(); stage=e.get('stage')
    if stage not in ('filled','sending'): continue
    if leg=='SHORT' and side!='SELL':
        print('LEAK_SIDE', e)
    if leg in ('LONG1','LONG2') and side!='BUY':
        print('LEAK_SIDE', e)

# Entry without 15m gain? hard from logs — grep entry qualify
print('\n=== ENTRY / GATE LOGS ===')
for ln in lines:
    if any(x in ln for x in ('entry qualify','live_entry','retrace','GAIN','blocked short_first','buy_blocked','wrong','orphan','SIBLING','paired hold blocks','LONG1 early','skipped')):
        if '2026-10-03' in ln or '2026-10-02' in ln:
            if 'scanner' in ln or 'EXEC' in ln:
                print(ln[:260])
PY
grep -E '2026-10-03.*(SHORT |LONG1 |LONG2 |INVALIDATION|PULLBACK|SMART_EXIT|RESCUE|paired hold|SIBLING|adopted|failed|EXEC_OK|EXEC_FAIL)' /var/log/bilshenz/binance-api.log | tail -n 80
'''
_,o,e=c.exec_command(CMD, timeout=90)
out=o.read().decode('utf-8','replace')
Path(__file__).with_name('_leak-forensic.txt').write_text(out, encoding='utf-8')
print(out.encode('ascii','replace').decode('ascii')[:16000])
err=e.read().decode('utf-8','replace')
if err.strip():
    print('STDERR', err.encode('ascii','replace').decode('ascii')[-1000:])
c.close()
