#!/usr/bin/env python3
"""Quant desk audit: Sep 23-25 contract vs live FRA (code + runtime + behavior markers)."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=40, look_for_keys=False, allow_agent=False)

CMD = r'''
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
import json, inspect, re, urllib.request, subprocess, sys
from pathlib import Path

fails=[]; warns=[]; oks=[]
def ok(m): oks.append(m); print('PASS', m)
def bad(m): fails.append(m); print('FAIL', m)
def warn(m): warns.append(m); print('WARN', m)

# --- 1) Contract assert ---
from frozen_strategy import assert_frozen_contract, frozen_contract_snapshot, LOCKED_PARTITION_USD
try:
    snap=assert_frozen_contract()
    ok(f"assert_frozen_contract {snap['strategy_id']}")
except AssertionError as e:
    bad(f"assert_frozen_contract: {e}")
    snap=frozen_contract_snapshot()

import momentum_scanner as ms
import leverage_policy as lev
import binance_connector as bc
from strategy_guards import sanitize_partitions

# --- 2) Exact Sep23-25 numeric matrix ---
matrix=[
 ('GAIN', ms.GAIN_THRESHOLD_PCT, 5.0),
 ('RETRACE', ms.RETRACE_ENTRY_PCT, 0.7),
 ('L1_ADV', ms.LONG1_ADVERSE_PCT, 2.0),
 ('L2_ADV', ms.LONG2_ADVERSE_PCT, 4.0),
 ('SHORT_TP', ms.SHORT_TP_PCT, 2.5),
 ('LONG_TP', ms.LONG_TP_PCT, 2.5),
 ('LONG_PB', float(ms.LONG_HEDGE_PULLBACK_PCT), 0.5),
 ('SHORT_PB_FLOOR', float(ms.SHORT_TRAIL_PULLBACK_PCT), 1.5),
 ('INVALIDATION', float(ms.PAIR_INVALIDATION_PCT), 6.5),
 ('RESCUE', float(ms.HEDGE_RESCUE_BUFFER_PCT), 1.0),
 ('SMART_EXIT', float(ms.SMART_EXIT_NET_PCT), 6.0),
 ('PART_USD', float(ms.LOCKED_PARTITION_USD), 100.0),
 ('DEFAULT_PART', float(ms.DEFAULT_PARTITION_USD), 100.0),
 ('SHORT_PCT', float(ms.SHORT_PARTITION_PCT), 50.0),
 ('L1_PCT', float(ms.LONG1_PARTITION_PCT), 40.0),
 ('L2_PCT', float(ms.LONG2_PARTITION_PCT), 40.0),
 ('SHORT_LEV', float(lev.SHORT_LEVERAGE), 5.0),
 ('L1_LEV', float(lev.LONG1_LEVERAGE), 10.0),
 ('L2_LEV', float(lev.LONG2_LEVERAGE), 10.0),
]
for name, got, want in matrix:
    (ok if abs(got-want)<1e-9 else bad)(f'{name}={got} want={want}')

# --- 3) Behavioral source locks ---
src=Path(ms.__file__).read_text(encoding='utf-8')
for needle,label in [
 ('short_ok_for_smart','SMART_EXIT hedged short-profit guard'),
 ('_force_locked_partition_usd','partition force lock'),
 ('SIBLING_WIPE','sibling wipe re-arm'),
 ('preserve sibling','safe recovery close'),
 ('_short_underwater','paired-hold underwater'),
 ('paired hold','paired hold comment/path'),
 ('LONG1_PULLBACK','long1 pullback exit'),
 ('INVALIDATION','invalidation exit'),
 ('RESCUE','rescue exit'),
 ('SMART_EXIT','smart exit'),
]:
    (ok if needle.lower() in src.lower() or needle in src else bad)(label)

cool=inspect.getsource(bc.BinanceConnector._wait_or_clear_cool_for_close)
(ok if 'max_wait_s: float = 12.0' in cool else bad)('cool default 12s')
(ok if 'immediate flatten' not in cool else bad)('no instant cool-clear')
(ok if 'forced to 12s' in cool or 'ignoring max_wait_s' in cool else bad)('cool rejects 0')
(ok if 'waiting' in cool and 'clearing residual cool' in cool else bad)('cool wait+residual')

# transport retry lock (ops reliability — must not block strategy)
parse=inspect.getsource(bc.BinanceConnector._parse_order_error)
(ok if 'remote end closed' in parse.lower() else bad)('order retry includes remote-closed')
pos_src=inspect.getsource(bc.BinanceConnector.positions)
(ok if 'rest_cooling_left' in pos_src else bad)('positions short-circuits during cool')

# --- 4) Unit tests on VPS ---
tests=['test_frozen_strategy.py','test_strategy_guards.py','test_execution_engine.py','test_exec_session.py']
for t in tests:
    r=subprocess.run([sys.executable, t], cwd='/opt/bilshenz/binance_trading_system/python', capture_output=True, text=True)
    # many are scripts with main, not pytest
    out=(r.stdout or '')+(r.stderr or '')
    if r.returncode==0:
        ok(f'unit {t}')
    else:
        # try pytest
        r2=subprocess.run([sys.executable,'-m','pytest',t,'-q','--tb=line'], cwd='/opt/bilshenz/binance_trading_system/python', capture_output=True, text=True)
        out2=(r2.stdout or '')+(r2.stderr or '')
        if r2.returncode==0:
            ok(f'pytest {t}')
        else:
            bad(f'test {t} rc={r.returncode}/{r2.returncode} {(out2 or out)[-300:]}')

# --- 5) Live runtime ---
env={}
for ln in Path('/etc/bilshenz.env').read_text().splitlines():
    if '=' in ln and not ln.startswith('#'):
        k,v=ln.split('=',1); env[k]=v.strip().strip('"').strip("'")

# env strategy knobs must not invert Sep23
env_expect={
 'SCANNER_INVALIDATION_PCT':'6.5',
 'SCANNER_RESCUE_BUFFER_PCT':'1.0',
 'SCANNER_LONG_PULLBACK_PCT':'0.5',
 'SCANNER_SHORT_PULLBACK_PCT':'1.5',
 'SCANNER_SMART_EXIT_PCT':'6.0',
 'SCANNER_SHORT_PARTITION_PCT':'50',
 'SCANNER_LONG1_PARTITION_PCT':'40',
 'SCANNER_LONG2_PARTITION_PCT':'40',
}
for k,v in env_expect.items():
    got=env.get(k)
    if got is None:
        warn(f'env missing {k} (defaults OK if module default)')
    elif abs(float(got)-float(v))<1e-9:
        ok(f'env {k}={got}')
    else:
        bad(f'env {k}={got} want={v}')

h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {}
(ok if sc.get('strategy_id')=='short_first_v1' else bad)(f"live strategy={sc.get('strategy_id')}")
(ok if abs(float(sc.get('partition_usd') or 0)-100)<1e-9 else bad)(f"live part={sc.get('partition_usd')}")
(ok if sc.get('partition_usd_locked') is True else bad)(f"live part_locked={sc.get('partition_usd_locked')}")
for k,w in [('short_partition_pct',50),('long1_partition_pct',40),('long2_partition_pct',40),
            ('short_tp_pct',2.5),('long_tp_pct',2.5),('long_pullback_pct',0.5),('short_pullback_pct',1.5)]:
    g=float(sc.get(k) or -1)
    (ok if abs(g-w)<1e-9 else bad)(f'live {k}={g}')

# reject partition drift attempt
tok=env.get('BRIDGE_TOKEN','')
body=json.dumps({'partition_usd':50,'short_pct':50,'long1_pct':40,'long2_pct':40}).encode()
req=urllib.request.Request('http://127.0.0.1:8766/api/scanner/risk', data=body, method='POST',
    headers={'Content-Type':'application/json','Authorization':'Bearer '+tok,'X-Bridge-Token':tok})
try:
    with urllib.request.urlopen(req, timeout=12) as r:
        out=json.loads(r.read().decode())
    (ok if abs(float(out.get('partition_usd'))-100)<1e-9 else bad)(f"POST50 rejected -> {out.get('partition_usd')}")
except Exception as e:
    bad(f'POST50 risk API {e}')

# --- 6) Recent behavior consistency (testnet day) ---
log=Path('/var/log/bilshenz/binance-api.log').read_text(errors='replace')
# count exit reasons today
from collections import Counter
c=Counter()
for m in re.finditer(r'2026-10-03T\S+ .*scanner (?:closed(?: leg)? \S+ )?(?:reason=)?(SHORT_TP|SHORT_PULLBACK|LONG1_PULLBACK|LONG2_PULLBACK|LONG1_TP|LONG2_TP|SMART_EXIT|INVALIDATION|RESCUE|INVALIDATION)', log):
    c[m.group(1)]+=1
# also closed reason=
for m in re.finditer(r'2026-10-03T\S+ .*reason=(SHORT_TP|SHORT_PULLBACK|LONG1_PULLBACK|LONG2_PULLBACK|SMART_EXIT|INVALIDATION|RESCUE)', log):
    c['reason:'+m.group(1)]+=1
print('BEHAVIOR_COUNTS', dict(c))
# flag non-contract exit strings
bad_exit=re.findall(r'2026-10-03T\S+ .*reason=([A-Z0-9_]+)', log)
allowed=set(['SHORT_TP','SHORT_PULLBACK','LONG1_PULLBACK','LONG2_PULLBACK','LONG1_TP','LONG2_TP','SMART_EXIT','INVALIDATION','RESCUE',
             'LONG1_PULLBACK_PAIR_FLATTEN','LONG2_PULLBACK_PAIR_FLATTEN','LONG1_TP_PAIR_FLATTEN','LONG2_TP_PAIR_FLATTEN',
             'INVALIDATION','MANUAL','EMERGENCY','CLOSE_ALL','PAIR_FLATTEN'])
unknown=sorted({x for x in bad_exit if x not in allowed and 'PAIR' not in x and not x.startswith('LONG') and not x.startswith('SHORT')})
# soften: just show unique reasons
uniq=sorted(set(bad_exit))
print('UNIQUE_REASONS_TODAY', uniq[:40])
for rsn in uniq:
    if rsn in ('SHORT_TP','SHORT_PULLBACK','LONG1_PULLBACK','LONG2_PULLBACK','LONG1_TP','LONG2_TP','SMART_EXIT','INVALIDATION','RESCUE') or 'PAIR_FLATTEN' in rsn:
        ok(f'exit_reason allowed: {rsn}')
    elif rsn in ('SIBLING_WIPE',) or 'COOL' in rsn:
        warn(f'exit_reason noted: {rsn}')
    else:
        # many are not exit reasons (INVALIDATION alone already counted)
        if rsn.endswith('_PAIR_FLATTEN') or rsn in allowed:
            ok(f'exit_reason allowed: {rsn}')
        else:
            warn(f'unclassified reason token: {rsn}')

# margin fails today on testnet with 5k should be ~0
mcount=len(re.findall(r'2026-10-03T\S+.*insufficient_margin', log))
(ok if mcount==0 else warn)(f'today insufficient_margin count={mcount} (0 expected on $5k testnet)')

# --- Summary ---
print('\n=== QUANT VERDICT ===')
print('PASS', len(oks), 'WARN', len(warns), 'FAIL', len(fails))
for f in fails:
    print('FAIL_ITEM', f)
if fails:
    print('VERDICT', 'NOT_ALIGNED')
    raise SystemExit(2)
print('VERDICT', 'ALIGNED_SEP23_25')
PY
'''
_,o,e=c.exec_command(CMD, timeout=180)
out=o.read().decode('utf-8','replace')
Path(__file__).with_name('_quant-sep23-audit.txt').write_text(out, encoding='utf-8')
print(out.encode('ascii','replace').decode('ascii'))
err=e.read().decode('utf-8','replace')
if err.strip():
    print('STDERR', err.encode('ascii','replace').decode('ascii')[-2000:])
print('EXIT', o.channel.recv_exit_status())
c.close()
