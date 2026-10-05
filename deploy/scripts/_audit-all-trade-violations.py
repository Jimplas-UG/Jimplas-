#!/usr/bin/env python3
"""Full trade-vs-rules forensic for FRA logs (Sep23-25 short_first_v1)."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=40, look_for_keys=False, allow_agent=False)

CMD = r'''
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
import re
from collections import defaultdict, Counter
from pathlib import Path
from dataclasses import dataclass, field

LOGS = []
for p in (Path('/var/log/bilshenz/binance-api.log'), Path('/var/log/bilshenz/binance-api.log.1')):
    if p.exists():
        LOGS.append(p.read_text(errors='replace'))
text = '\n'.join(LOGS)

# Parse chronological trade lifecycle events
# Patterns
P_SHORT = re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner SHORT (?P<sym>\S+) qty=(?P<qty>[\d.]+) @ (?P<px>[\d.eE+-]+)')
P_L1 = re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner LONG1 (?P<sym>\S+) qty=(?P<qty>[\d.]+) @ (?P<px>[\d.eE+-]+)')
P_L2 = re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner LONG2 (?P<sym>\S+) qty=(?P<qty>[\d.]+) @ (?P<px>[\d.eE+-]+)')
P_ADOPT_S = re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner adopted exchange SHORT (?P<sym>\S+) qty=(?P<qty>[\d.]+) @ (?P<px>[\d.eE+-]+)')
P_ADOPT_L1 = re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner adopted exchange LONG1 (?P<sym>\S+) qty=(?P<qty>[\d.]+) @ (?P<px>[\d.eE+-]+)')
P_ADOPT_L2 = re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner adopted exchange LONG2 (?P<sym>\S+) qty=(?P<qty>[\d.]+) @ (?P<px>[\d.eE+-]+)')
P_CLOSE_LEG = re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner closed leg (?P<sym>\S+) (?P<leg>\S+) reason=(?P<reason>\S+)')
P_CLOSE = re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner closed (?P<sym>\S+) reason=(?P<reason>\S+)')
P_PB = re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner (?P<sym>\S+) (?P<kind>LONG1_PULLBACK|LONG2_PULLBACK|SHORT_PULLBACK) (?P<pct>[\d.]+)% \([^)]*price=(?P<px>[\d.eE+-]+)[^)]*entry=(?P<entry>[\d.eE+-]+)')
P_INV = re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner (?P<sym>\S+) INVALIDATION adverse=(?P<adv>[\d.]+)')
P_FAIL = re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) WARNING \[momentum_scanner\] scanner (?P<leg>SHORT|LONG1|LONG2) failed (?P<sym>\S+): (?P<err>.+?)(?:\s+latency|$)')
P_LEV = re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[binance_connector\] exchange leverage (?P<sym>\S+) set (?P<fr>\d+)x -> (?P<to>\d+)x')
P_EXEC = re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[execution_engine\] EXEC_OK coin=(?P<sym>\S+) side=(?P<side>\S+) qty=(?P<qty>[\d.]+) fill=(?P<fill>[\d.eE+-]+).*manual=(?P<manual>True|False)')
P_SMART = re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner (?P<sym>\S+) SMART_EXIT')
P_RESCUE = re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner (?P<sym>\S+) RESCUE')
P_PAIR = re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner (?P<sym>\S+) paired hold blocks solo (?P<reason>\S+)')

events=[]
for rx, kind in [
    (P_SHORT,'SHORT'),(P_L1,'LONG1'),(P_L2,'LONG2'),
    (P_ADOPT_S,'ADOPT_SHORT'),(P_ADOPT_L1,'ADOPT_LONG1'),(P_ADOPT_L2,'ADOPT_LONG2'),
    (P_CLOSE_LEG,'CLOSE_LEG'),(P_CLOSE,'CLOSE'),(P_PB,'PULLBACK'),
    (P_INV,'INVALIDATION'),(P_FAIL,'FAIL'),(P_LEV,'LEV'),
    (P_EXEC,'EXEC'),(P_SMART,'SMART'),(P_RESCUE,'RESCUE'),(P_PAIR,'PAIR_BLOCK'),
]:
    for m in rx.finditer(text):
        d=m.groupdict(); d['kind']=kind; events.append(d)
events.sort(key=lambda d: d['ts'])

# Reconstruct trades: from SHORT/ADOPT_SHORT until CLOSE (or next SHORT same sym)
@dataclass
class Trade:
    sym: str
    short_ts: str = ''
    short_px: float = 0.0
    short_qty: float = 0.0
    adopted: bool = False
    manual_hint: bool = False
    l1_ts: str = ''
    l1_px: float = 0.0
    l2_ts: str = ''
    l2_px: float = 0.0
    l1_closed_reason: str = ''
    l2_closed_reason: str = ''
    end_reason: str = ''
    end_ts: str = ''
    fails: list = field(default_factory=list)
    lev_changes: list = field(default_factory=list)
    pullbacks: list = field(default_factory=list)
    violations: list = field(default_factory=list)
    notes: list = field(default_factory=list)

open_trades: dict[str, Trade] = {}
completed: list[Trade] = []

def finish(sym, reason, ts):
    t=open_trades.pop(sym, None)
    if not t: return
    t.end_reason=reason; t.end_ts=ts
    completed.append(t)

for e in events:
    kind=e['kind']; sym=e.get('sym','')
    if kind in ('SHORT','ADOPT_SHORT'):
        if sym in open_trades:
            # overlapping short without close — flag
            open_trades[sym].violations.append('OVERLAPPING_SHORT_WITHOUT_CLOSE')
            finish(sym, 'IMPLIED_REPLACE', e['ts'])
        t=Trade(sym=sym, short_ts=e['ts'], short_px=float(e['px']), short_qty=float(e['qty']),
                adopted=(kind=='ADOPT_SHORT'))
        open_trades[sym]=t
    elif kind=='LONG1' or kind=='ADOPT_LONG1':
        t=open_trades.get(sym)
        if not t:
            # Long1 with no tracked short
            t=Trade(sym=sym); t.violations.append('LONG1_WITHOUT_TRACKED_SHORT'); open_trades[sym]=t
        t.l1_ts=e['ts']; t.l1_px=float(e['px'])
        if kind=='ADOPT_LONG1': t.notes.append('adopted_l1')
    elif kind=='LONG2' or kind=='ADOPT_LONG2':
        t=open_trades.get(sym)
        if not t:
            t=Trade(sym=sym); t.violations.append('LONG2_WITHOUT_TRACKED_SHORT'); open_trades[sym]=t
        t.l2_ts=e['ts']; t.l2_px=float(e['px'])
        if kind=='ADOPT_LONG2': t.notes.append('adopted_l2')
    elif kind=='CLOSE_LEG':
        t=open_trades.get(sym)
        if not t: continue
        if e['leg']=='long1': t.l1_closed_reason=e['reason']
        if e['leg']=='long2': t.l2_closed_reason=e['reason']
    elif kind=='CLOSE':
        finish(sym, e['reason'], e['ts'])
    elif kind=='INVALIDATION':
        t=open_trades.get(sym)
        if t: t.notes.append(f"inv_mark={e['adv']}")
        # close usually follows
    elif kind=='PULLBACK':
        t=open_trades.get(sym)
        if t:
            t.pullbacks.append((e['kind'], float(e['pct']), float(e['px']), float(e['entry'])))
    elif kind=='FAIL':
        t=open_trades.get(sym)
        if t: t.fails.append((e['leg'], e['err'][:60]))
        else:
            # fail before open tracked
            pass
    elif kind=='LEV':
        t=open_trades.get(sym)
        if t: t.lev_changes.append((int(e['fr']), int(e['to']), e['ts']))
    elif kind=='EXEC':
        if e.get('manual')=='True' and e.get('side')=='SELL':
            t=open_trades.get(sym)
            if t: t.manual_hint=True
    elif kind=='SMART':
        t=open_trades.get(sym)
        if t: t.notes.append('SMART_EXIT_SIGNAL')
    elif kind=='RESCUE':
        t=open_trades.get(sym)
        if t: t.notes.append('RESCUE_SIGNAL')

# still open
still=list(open_trades.values())

# Score violations vs Sep23 rules
L1_MIN, L2_MIN, INV = 2.0, 4.0, 6.5
# allow small fill slip
L1_EARLY, L2_EARLY = 1.85, 3.70

def score(t: Trade):
    v=t.violations
    if t.short_px<=0 and (t.l1_px or t.l2_px):
        v.append('HEDGE_WITHOUT_SHORT_ENTRY')
    if t.l1_px>0 and t.short_px>0:
        adv=(t.l1_px/t.short_px - 1.0)*100.0
        if adv < L1_EARLY:
            v.append(f'LONG1_EARLY adv={adv:.2f}% (<2%)')
        elif adv > INV + 0.5:
            v.append(f'LONG1_AFTER_INVALIDATION_ZONE adv={adv:.2f}%')
        t.notes.append(f'l1_adv={adv:.2f}%')
    if t.l2_px>0 and t.short_px>0:
        adv=(t.l2_px/t.short_px - 1.0)*100.0
        if adv < L2_EARLY:
            v.append(f'LONG2_EARLY adv={adv:.2f}% (<4%)')
        t.notes.append(f'l2_adv={adv:.2f}%')
    # Long2 without Long1 ever (and no l1 closed reason → never armed)
    if t.l2_px>0 and t.l1_px<=0 and not t.l1_closed_reason:
        v.append('LONG2_WITHOUT_LONG1')
    # Paired-hold leak: LONG pullback while price still >= short entry (short underwater)
    for kind,pct,px,entry in t.pullbacks:
        if kind.startswith('LONG') and t.short_px>0 and px >= t.short_px - 1e-12:
            v.append(f'{kind}_WHILE_SHORT_UNDERWATER px={px} short={t.short_px}')
    # Hedge dumped then invalidation (capital path leak / criteria pain)
    if t.end_reason=='INVALIDATION':
        if t.l1_closed_reason in ('LONG1_PULLBACK','LONG1_TP') and t.l2_px<=0:
            v.append('NAKED_SHORT_TO_INVALIDATION_AFTER_L1_EXIT')
        if t.l1_closed_reason in ('LONG1_PULLBACK','LONG1_TP') and t.l2_px>0 and t.l2_closed_reason in ('LONG2_PULLBACK','LONG2_TP',''):
            # L1 gone, L2 maybe still or also gone
            if not t.l2_closed_reason or t.l2_closed_reason in ('LONG2_PULLBACK','LONG2_TP'):
                v.append('HEDGE_EXIT_THEN_INVALIDATION')
        if t.l1_px<=0 and t.l2_px<=0:
            v.append('INVALIDATION_WITH_NO_HEDGES')
        if any(leg=='LONG1' and 'insufficient_margin' in err for leg,err in t.fails):
            v.append('INVALIDATION_AFTER_L1_MARGIN_FAIL')
        if any(leg=='LONG2' and 'insufficient_margin' in err for leg,err in t.fails):
            v.append('INVALIDATION_AFTER_L2_MARGIN_FAIL')
    # Leverage forced up to 10x while naked (from logs)
    for fr,to,ts in t.lev_changes:
        if fr==5 and to==10 and t.l1_px<=0 and t.l2_px<=0:
            # 10x bump before any hedge = leak
            v.append('NAKED_SHORT_LEVERAGE_5_TO_10')
        if to==10 and t.l1_px<=0 and t.l2_px<=0 and not t.l1_ts:
            v.append('NAKED_SHORT_HELD_AT_10X')
    # Failures that break criteria path
    for leg,err in t.fails:
        if 'insufficient_margin' in err:
            v.append(f'{leg}_MARGIN_BLOCK')
        if 'Remote end closed' in err or 'FORWARD_DRY_RUN' in err or '-2015' in err:
            v.append(f'{leg}_EXEC_FAIL:{err[:40]}')
    # Adopted manual short treated as strategy
    if t.adopted and t.manual_hint:
        v.append('MANUAL_SHORT_ADOPTED_AS_STRATEGY')
    # Dedup
    t.violations=list(dict.fromkeys(v))

for t in completed+still:
    score(t)

# Report
print('=== UNIVERSE ===')
print('completed_trades', len(completed), 'still_open', len(still), 'events', len(events))

# Per-trade summary
print('\n=== TRADE LEDGER (violations highlighted) ===')
all_trades=completed+still
# focus recent-ish: last 40 completed + open
show=completed[-40:]+still
for t in show:
    l1a=''; l2a=''
    if t.short_px and t.l1_px: l1a=f'{(t.l1_px/t.short_px-1)*100:.2f}%'
    if t.short_px and t.l2_px: l2a=f'{(t.l2_px/t.short_px-1)*100:.2f}%'
    print(f"\n{t.sym} short@{t.short_px} ts={t.short_ts[-8:] if t.short_ts else '-'} adopt={t.adopted} manual={t.manual_hint}")
    print(f"  L1@{t.l1_px or '-'} adv={l1a or '-'} closed={t.l1_closed_reason or '-'} | L2@{t.l2_px or '-'} adv={l2a or '-'} closed={t.l2_closed_reason or '-'}")
    print(f"  END {t.end_reason or 'OPEN'} @{t.end_ts[-8:] if t.end_ts else '-'} fails={t.fails[:3]} lev={t.lev_changes[:3]}")
    if t.violations:
        print('  VIOLATIONS:', '; '.join(t.violations))
    else:
        print('  VIOLATIONS: none')

# Aggregate
vc=Counter()
for t in all_trades:
    for v in t.violations:
        # normalize
        key=v.split(' adv=')[0].split(' px=')[0].split(':')[0]
        if key.startswith('LONG1_EARLY'): key='LONG1_EARLY'
        if key.startswith('LONG2_EARLY'): key='LONG2_EARLY'
        if key.startswith('LONG1_PULLBACK_WHILE'): key='LONG_PULLBACK_WHILE_SHORT_UNDERWATER'
        if key.startswith('LONG2_PULLBACK_WHILE'): key='LONG_PULLBACK_WHILE_SHORT_UNDERWATER'
        if key.startswith('LONG1_MARGIN'): key='LONG1_MARGIN_BLOCK'
        if key.startswith('LONG2_MARGIN'): key='LONG2_MARGIN_BLOCK'
        if key.startswith('SHORT_EXEC_FAIL'): key='SHORT_EXEC_FAIL'
        if key.startswith('LONG1_EXEC_FAIL'): key='LONG1_EXEC_FAIL'
        if key.startswith('LONG2_EXEC_FAIL'): key='LONG2_EXEC_FAIL'
        vc[key]+=1

print('\n=== VIOLATION RANKING (all reconstructed trades) ===')
total_violating=sum(1 for t in all_trades if t.violations)
print('trades_total', len(all_trades), 'trades_with_any_violation', total_violating)
for k,n in vc.most_common(25):
    print(f'{n:4d}  {k}')

# Common path patterns
print('\n=== COMMON PATH PATTERNS ===')
paths=Counter()
for t in all_trades:
    if t.end_reason=='INVALIDATION' and t.l1_closed_reason=='LONG1_PULLBACK':
        paths['L1_PULLBACK -> (L2?) -> INVALIDATION']+=1
    if t.end_reason=='SHORT_TP' and t.l1_px<=0:
        paths['SHORT_ONLY -> SHORT_TP']+=1
    if t.end_reason=='SHORT_TP' and t.l1_px>0:
        paths['HEDGED -> SHORT_TP']+=1
    if any('MARGIN_BLOCK' in v for v in t.violations):
        paths['MARGIN_BLOCKED_HEDGE']+=1
    if any('NAKED_SHORT_LEVERAGE' in v or 'HELD_AT_10X' in v for v in t.violations):
        paths['NAKED_SHORT_AT_10X']+=1
    if t.end_reason=='INVALIDATION' and t.l1_px<=0 and t.l2_px<=0:
        paths['NAKED_SHORT -> INVALIDATION']+=1
for k,n in paths.most_common():
    print(f'{n:4d}  {k}')

print('\n=== TOP COMMON VIOLATION ===')
if vc:
    top,n=vc.most_common(1)[0]
    print(f'{top}  count={n}  ({100*n/max(len(all_trades),1):.0f}% of trades)')
else:
    print('NONE')
PY
'''
_,o,e=c.exec_command(CMD, timeout=120)
out=o.read().decode('utf-8','replace')
Path(__file__).with_name('_trade-violations-report.txt').write_text(out, encoding='utf-8')
print(out.encode('ascii','replace').decode('ascii'))
err=e.read().decode('utf-8','replace')
if err.strip():
    print('STDERR', err.encode('ascii','replace').decode('ascii')[-2000:])
c.close()
