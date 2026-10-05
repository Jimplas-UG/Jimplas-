#!/usr/bin/env python3
"""Scan FRA logs + live code for Sep23 rule breaks BEYOND the 3 already locked."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=40, look_for_keys=False, allow_agent=False)

CMD = r'''
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
import re, json, urllib.request, inspect
from collections import Counter, defaultdict
from pathlib import Path
from dataclasses import dataclass, field

KNOWN = {
    'NAKED_SHORT_LEVERAGE_5_TO_10',
    'NAKED_SHORT_HELD_AT_10X',
    'HEDGE_EXIT_THEN_INVALIDATION',
    'OVERLAPPING_SHORT_WITHOUT_CLOSE',
    'LONG_PULLBACK_WHILE_SHORT_UNDERWATER',  # subset of hedge-exit path
}

text=''
for p in (Path('/var/log/bilshenz/binance-api.log'), Path('/var/log/bilshenz/binance-api.log.1')):
    if p.exists(): text += p.read_text(errors='replace')+'\n'

# --- Parse events ---
P_SHORT=re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner SHORT (?P<sym>\S+) qty=(?P<qty>[\d.]+) @ (?P<px>[\d.eE+-]+)')
P_L1=re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner LONG1 (?P<sym>\S+) qty=(?P<qty>[\d.]+) @ (?P<px>[\d.eE+-]+)')
P_L2=re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner LONG2 (?P<sym>\S+) qty=(?P<qty>[\d.]+) @ (?P<px>[\d.eE+-]+)')
P_ADOPT_S=re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner adopted exchange SHORT (?P<sym>\S+) qty=(?P<qty>[\d.]+) @ (?P<px>[\d.eE+-]+)')
P_CLOSE_LEG=re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner closed leg (?P<sym>\S+) (?P<leg>\S+) reason=(?P<reason>\S+)')
P_CLOSE=re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner closed (?P<sym>\S+) reason=(?P<reason>\S+)')
P_PB=re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner (?P<sym>\S+) (?P<kind>LONG1_PULLBACK|LONG2_PULLBACK|SHORT_PULLBACK) (?P<pct>[\d.]+)% \([^)]*price=(?P<px>[\d.eE+-]+)[^)]*entry=(?P<entry>[\d.eE+-]+)')
P_INV=re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[momentum_scanner\] scanner (?P<sym>\S+) INVALIDATION adverse=(?P<adv>[\d.]+)')
P_FAIL=re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) WARNING \[momentum_scanner\] scanner (?P<leg>SHORT|LONG1|LONG2) failed (?P<sym>\S+): (?P<err>.+?)(?:\s+latency|$)')
P_LEV=re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[binance_connector\] exchange leverage (?P<sym>\S+) set (?P<fr>\d+)x -> (?P<to>\d+)x')
P_EXEC=re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) INFO \[execution_engine\] EXEC_OK coin=(?P<sym>\S+) side=(?P<side>\S+) qty=(?P<qty>[\d.]+) fill=(?P<fill>[\d.eE+-]+).*manual=(?P<manual>True|False)')
P_SMART=re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) .*scanner (?P<sym>\S+) SMART_EXIT')
P_RESCUE=re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) .*scanner (?P<sym>\S+) RESCUE')
P_ORPHAN=re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) .*orphan', re.I)
P_SIBLING=re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) .*SIBLING_WIPE')
P_COOL=re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) .*immediate flatten')
P_PART=re.compile(r'(?P<ts>20\d\d-\d\d-\d\dT\S+) .*partition.*?\$(\d+(?:\.\d+)?)', re.I)

events=[]
for rx,kind in [(P_SHORT,'SHORT'),(P_L1,'LONG1'),(P_L2,'LONG2'),(P_ADOPT_S,'ADOPT_SHORT'),
                (P_CLOSE_LEG,'CLOSE_LEG'),(P_CLOSE,'CLOSE'),(P_PB,'PULLBACK'),(P_INV,'INV'),
                (P_FAIL,'FAIL'),(P_LEV,'LEV'),(P_EXEC,'EXEC'),(P_SMART,'SMART'),(P_RESCUE,'RESCUE'),
                (P_SIBLING,'SIBLING')]:
    for m in rx.finditer(text):
        d=m.groupdict(); d['kind']=kind; events.append(d)
events.sort(key=lambda d: d['ts'])

@dataclass
class Trade:
    sym:str; short_ts:str=''; short_px:float=0; short_qty:float=0; adopted:bool=False; manual:bool=False
    l1_ts:str=''; l1_px:float=0; l2_ts:str=''; l2_px:float=0
    l1_closed:str=''; l2_closed:str=''; end:str=''; end_ts:str=''
    fails:list=field(default_factory=list); lev:list=field(default_factory=list)
    pbs:list=field(default_factory=list); notes:list=field(default_factory=list)
    viol:list=field(default_factory=list)

open_t={}; done=[]
def fin(sym,reason,ts):
    t=open_t.pop(sym,None)
    if t: t.end=reason; t.end_ts=ts; done.append(t)

for e in events:
    k=e['kind']; sym=e.get('sym','')
    if k in ('SHORT','ADOPT_SHORT'):
        if sym in open_t:
            open_t[sym].viol.append('OVERLAPPING_SHORT_WITHOUT_CLOSE'); fin(sym,'IMPLIED_REPLACE',e['ts'])
        t=Trade(sym=sym, short_ts=e['ts'], short_px=float(e['px']), short_qty=float(e['qty']), adopted=k=='ADOPT_SHORT')
        open_t[sym]=t
    elif k=='LONG1':
        t=open_t.get(sym) or Trade(sym=sym); open_t[sym]=t
        if t.short_px<=0: t.viol.append('LONG1_WITHOUT_SHORT')
        t.l1_ts=e['ts']; t.l1_px=float(e['px'])
    elif k=='LONG2':
        t=open_t.get(sym) or Trade(sym=sym); open_t[sym]=t
        if t.short_px<=0: t.viol.append('LONG2_WITHOUT_SHORT')
        t.l2_ts=e['ts']; t.l2_px=float(e['px'])
    elif k=='CLOSE_LEG':
        t=open_t.get(sym)
        if not t: continue
        if e['leg']=='long1': t.l1_closed=e['reason']
        if e['leg']=='long2': t.l2_closed=e['reason']
    elif k=='CLOSE':
        fin(sym,e['reason'],e['ts'])
    elif k=='PULLBACK':
        t=open_t.get(sym)
        if t: t.pbs.append((e['kind'], float(e['pct']), float(e['px']), float(e['entry'])))
    elif k=='FAIL':
        t=open_t.get(sym)
        if t: t.fails.append((e['leg'], e['err'][:80]))
    elif k=='LEV':
        t=open_t.get(sym)
        if t: t.lev.append((int(e['fr']), int(e['to'])))
    elif k=='EXEC' and e.get('manual')=='True' and e.get('side')=='SELL':
        t=open_t.get(sym)
        if t: t.manual=True
    elif k=='INV':
        t=open_t.get(sym)
        if t: t.notes.append(f"inv={e['adv']}")
    elif k=='SIBLING':
        t=open_t.get(sym)
        if t: t.notes.append('SIBLING_WIPE')

all_t=done+list(open_t.values())
L1_EARLY,L2_EARLY,INV=1.85,3.70,6.5

for t in all_t:
    v=t.viol
    if t.l1_px>0 and t.short_px>0:
        adv=(t.l1_px/t.short_px-1)*100
        t.notes.append(f'l1_adv={adv:.2f}')
        if adv<L1_EARLY: v.append(f'LONG1_EARLY_{adv:.2f}')
        if adv>=INV: v.append(f'LONG1_PAST_INVALIDATION_{adv:.2f}')
    if t.l2_px>0 and t.short_px>0:
        adv=(t.l2_px/t.short_px-1)*100
        t.notes.append(f'l2_adv={adv:.2f}')
        if adv<L2_EARLY: v.append(f'LONG2_EARLY_{adv:.2f}')
        if adv>=INV: v.append(f'LONG2_PAST_INVALIDATION_{adv:.2f}')
    if t.l2_px>0 and t.l1_px<=0 and not t.l1_closed:
        v.append('LONG2_WITHOUT_LONG1')
    # Wrong order: L2 before L1 timestamps
    if t.l1_ts and t.l2_ts and t.l2_ts < t.l1_ts:
        v.append('LONG2_BEFORE_LONG1_TIME')
    for kind,pct,px,entry in t.pbs:
        if kind.startswith('LONG') and t.short_px>0 and px>=t.short_px-1e-12:
            v.append('LONG_PULLBACK_WHILE_SHORT_UNDERWATER')
        if kind=='SHORT_PULLBACK' and (t.l1_px or t.l2_px) and not t.l1_closed and not t.l2_closed:
            # short trail while hedges still open — close_all is OK by contract
            pass
        if kind=='SHORT_PULLBACK' and t.l1_px<=0 and t.l2_px<=0 and t.short_px>0:
            # naked short trail — contract forbids trail while recovery still eligible
            # if ended SHORT_PULLBACK with no hedges ever, recovery was still eligible → VIOLATION
            if t.end=='SHORT_PULLBACK':
                v.append('NAKED_SHORT_TRAIL_WHILE_RECOVERY_ELIGIBLE')
    if t.end=='INVALIDATION':
        if t.l1_closed in ('LONG1_PULLBACK','LONG1_TP'):
            v.append('HEDGE_EXIT_THEN_INVALIDATION')
        if t.l1_px<=0 and t.l2_px<=0:
            v.append('INVALIDATION_WITH_NO_HEDGES')
    for fr,to in t.lev:
        if fr==5 and to==10 and t.l1_px<=0 and not t.l1_ts:
            v.append('NAKED_SHORT_LEVERAGE_5_TO_10')
        if to not in (5,10):
            v.append(f'NON_POLICY_LEVERAGE_{to}x')
    for leg,err in t.fails:
        if 'insufficient_margin' in err: v.append(f'{leg}_MARGIN_BLOCK')
        if 'Remote end closed' in err: v.append(f'{leg}_CONN_DROP_NO_RETRY')
        if '-2015' in err or 'Invalid API' in err: v.append(f'{leg}_AUTH_FAIL')
        if 'FORWARD_DRY_RUN' in err: v.append(f'{leg}_DRY_RUN_BLOCK')
    if t.adopted and t.manual:
        v.append('MANUAL_SHORT_ADOPTED_AS_STRATEGY')
    # sizing sanity: short qty * short_px / 5 ≈ $50 margin for $100 part; allow wide band
    if t.short_px>0 and t.short_qty>0:
        notional=t.short_qty*t.short_px
        margin_at_5=notional/5.0
        # expected ~50 for $100*50%; flag extreme outliers
        if margin_at_5 < 20 or margin_at_5 > 120:
            v.append(f'SHORT_SIZE_OUTLIER_margin5={margin_at_5:.1f}')
    if t.l1_px>0 and t.short_qty>0 and t.l1_ts:
        # rough: L1 notional/10 vs short notional/5 should be ~0.8 (40/50)
        pass
    t.viol=list(dict.fromkeys(v))

# Aggregate excluding the known-3 family for "other"
vc=Counter(); other=Counter()
for t in all_t:
    for v in t.viol:
        key=v
        for pref in ('LONG1_EARLY','LONG2_EARLY','LONG1_PAST_INVALIDATION','LONG2_PAST_INVALIDATION',
                     'SHORT_SIZE_OUTLIER','NON_POLICY_LEVERAGE','LONG1_MARGIN','LONG2_MARGIN','SHORT_MARGIN',
                     'LONG1_CONN','LONG2_CONN','SHORT_CONN','LONG1_AUTH','LONG2_AUTH','SHORT_AUTH',
                     'LONG1_DRY','LONG2_DRY','SHORT_DRY'):
            if v.startswith(pref): key=pref; break
        vc[key]+=1
        if key not in KNOWN and not key.startswith('NAKED_SHORT_LEVERAGE') and not key.startswith('NAKED_SHORT_HELD'):
            # map known family
            if key in ('HEDGE_EXIT_THEN_INVALIDATION','OVERLAPPING_SHORT_WITHOUT_CLOSE','LONG_PULLBACK_WHILE_SHORT_UNDERWATER'):
                pass
            else:
                other[key]+=1

print('=== TRADES ===', len(all_t))
print('\n=== ALL VIOLATION COUNTS ===')
for k,n in vc.most_common():
    tag=' [LOCKED_3]' if k in KNOWN or 'NAKED_SHORT' in k or k=='HEDGE_EXIT_THEN_INVALIDATION' or k=='OVERLAPPING_SHORT_WITHOUT_CLOSE' or k=='LONG_PULLBACK_WHILE_SHORT_UNDERWATER' else ' [OTHER]'
    print(f'{n:4d}{tag}  {k}')

print('\n=== OTHER RULE BREAKS (beyond the 3 locks) ===')
if not other:
    print('NONE_FOUND_IN_TRADE_LEDGER')
else:
    for k,n in other.most_common():
        print(f'{n:4d}  {k}')
        # examples
        ex=[t for t in all_t if any(v.startswith(k) or v==k for v in t.viol)][:3]
        for t in ex:
            detail=[v for v in t.viol if v.startswith(k) or v==k]
            print(f'      eg {t.sym} short@{t.short_px} end={t.end} {detail} notes={t.notes[:3]}')

# Code/static other risks
print('\n=== CODE / LIVE STATIC CHECKS (other Sep23 rules) ===')
import momentum_scanner as ms, leverage_policy as lev
from frozen_strategy import assert_frozen_contract
snap=assert_frozen_contract()
checks=[]
def chk(name, good, detail=''):
    print(('OK' if good else 'DRIFT'), name, detail)
    if not good: checks.append(name)

chk('partition_100', abs(ms.LOCKED_PARTITION_USD-100)<1e-9)
chk('gain_5', abs(ms.GAIN_THRESHOLD_PCT-5)<1e-9)
chk('retrace_0.7', abs(ms.RETRACE_ENTRY_PCT-0.7)<1e-9)
chk('l1_2', abs(ms.LONG1_ADVERSE_PCT-2)<1e-9)
chk('l2_4', abs(ms.LONG2_ADVERSE_PCT-4)<1e-9)
chk('inv_6.5', abs(ms.PAIR_INVALIDATION_PCT-6.5)<1e-9)
chk('smart_6', abs(ms.SMART_EXIT_NET_PCT-6)<1e-9)
chk('short_lev_5', lev.SHORT_LEVERAGE==5)
chk('long_lev_10', lev.LONG1_LEVERAGE==10)
cool=inspect.getsource(__import__('binance_connector').BinanceConnector._wait_or_clear_cool_for_close)
chk('cool_12', 'max_wait_s: float = 12.0' in cool)
chk('no_instant_flatten', 'immediate flatten' not in cool)
chk('short_ok_for_smart', 'short_ok_for_smart' in Path(ms.__file__).read_text())
chk('solo_hedge_lock', hasattr(ms.MomentumScanner,'_solo_hedge_exit_allowed'))

# Live
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {}
chk('live_part_100', abs(float(sc.get('partition_usd') or 0)-100)<1e-9, str(sc.get('partition_usd')))
chk('live_50_40_40', abs(float(sc.get('short_partition_pct') or 0)-50)<1e-9 and abs(float(sc.get('long1_partition_pct') or 0)-40)<1e-9)

# Ops issues that broke criteria path (not strategy knobs)
print('\n=== OPS BREAKS THAT MADE TRADES LOOK OFF-CRITERIA ===')
ops=Counter()
for t in all_t:
    for v in t.viol:
        if any(x in v for x in ('CONN_DROP','MARGIN_BLOCK','AUTH_FAIL','DRY_RUN','SIZE_OUTLIER')):
            ops[v.split('_')[0]+'_'+('_'.join(v.split('_')[1:3]) if '_' in v else v)] += 1
            # simpler
for k,n in Counter(
    v if any(x in v for x in ('CONN_DROP','MARGIN_BLOCK','AUTH_FAIL','DRY_RUN','SIZE_OUTLIER','PAST_INVALIDATION','LONG1_EARLY','LONG2_EARLY','WITHOUT','NAKED_SHORT_TRAIL','MANUAL_SHORT')) else None
    for t in all_t for v in t.viol
).most_common():
    if k: print(f'{n:4d}  {k}')

print('\n=== SUMMARY OTHER ===')
print('other_unique', len(other), 'other_total_hits', sum(other.values()))
print('static_drifts', checks or 'none')
PY
'''
_,o,e=c.exec_command(CMD, timeout=90)
out=o.read().decode('utf-8','replace')
Path(__file__).with_name('_other-violations.txt').write_text(out, encoding='utf-8')
print(out.encode('ascii','replace').decode('ascii'))
err=e.read().decode('utf-8','replace')
if err.strip():
    print('STDERR', err.encode('ascii','replace').decode('ascii')[-1500:])
c.close()
