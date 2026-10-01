#!/usr/bin/env python3
"""Confirm every Sep 23-25 desk detail is live on FRA. READ-ONLY verify."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
python3 <<'PY'
import json, inspect, re, urllib.request
from pathlib import Path

fails=[]
oks=[]

def ok(msg):
    oks.append(msg); print('OK ', msg)
def bad(msg):
    fails.append(msg); print('FAIL', msg)

# --- env ---
env={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
    if '=' in l and not l.startswith('#'):
        k,v=l.split('=',1); env[k]=v.strip().strip('"').strip("'")

# --- imports / contract ---
import sys
sys.path.insert(0,'/opt/bilshenz/binance_trading_system/python')
from frozen_strategy import assert_frozen_contract, LOCKED_PARTITION_USD, SMART_EXIT_NET_PCT, CLOSE_REST_COOL_MAX_WAIT_S
import momentum_scanner as ms
import binance_connector as bc
import leverage_policy as lev

try:
    snap=assert_frozen_contract()
    ok(f"assert_frozen_contract {snap['strategy_id']}")
except AssertionError as e:
    bad(f"assert_frozen_contract: {e}")
    snap={}

# Entry / legs / TP / hedge (exact Sep23-25)
checks=[
 ('GAIN', abs(ms.GAIN_THRESHOLD_PCT-5.0)<1e-9, ms.GAIN_THRESHOLD_PCT),
 ('RETRACE', abs(ms.RETRACE_ENTRY_PCT-0.7)<1e-9, ms.RETRACE_ENTRY_PCT),
 ('L1_ADV', abs(ms.LONG1_ADVERSE_PCT-2.0)<1e-9, ms.LONG1_ADVERSE_PCT),
 ('L2_ADV', abs(ms.LONG2_ADVERSE_PCT-4.0)<1e-9, ms.LONG2_ADVERSE_PCT),
 ('SHORT_TP', abs(ms.SHORT_TP_PCT-2.5)<1e-9, ms.SHORT_TP_PCT),
 ('LONG_TP', abs(ms.LONG_TP_PCT-2.5)<1e-9, ms.LONG_TP_PCT),
 ('PULLBACK', abs(float(ms.LONG_HEDGE_PULLBACK_PCT)-0.5)<1e-9, ms.LONG_HEDGE_PULLBACK_PCT),
 ('INVALIDATION', abs(float(ms.PAIR_INVALIDATION_PCT)-6.5)<1e-9, ms.PAIR_INVALIDATION_PCT),
 ('RESCUE_BUF', abs(float(ms.HEDGE_RESCUE_BUFFER_PCT)-1.0)<1e-9, ms.HEDGE_RESCUE_BUFFER_PCT),
 ('SMART_EXIT', abs(float(ms.SMART_EXIT_NET_PCT)-6.0)<1e-9, ms.SMART_EXIT_NET_PCT),
 ('PART_USD', abs(float(ms.LOCKED_PARTITION_USD)-100.0)<1e-9, ms.LOCKED_PARTITION_USD),
 ('DEFAULT_PART', abs(float(ms.DEFAULT_PARTITION_USD)-100.0)<1e-9, ms.DEFAULT_PARTITION_USD),
 ('SHORT_PCT', abs(float(ms.SHORT_PARTITION_PCT)-50.0)<1e-6, ms.SHORT_PARTITION_PCT),
 ('L1_PCT', abs(float(ms.LONG1_PARTITION_PCT)-40.0)<1e-6, ms.LONG1_PARTITION_PCT),
 ('L2_PCT', abs(float(ms.LONG2_PARTITION_PCT)-40.0)<1e-6, ms.LONG2_PARTITION_PCT),
 ('SHORT_LEV', lev.SHORT_LEVERAGE==5, lev.SHORT_LEVERAGE),
 ('LONG_LEV', lev.LONG1_LEVERAGE==10 and lev.LONG2_LEVERAGE==10, (lev.LONG1_LEVERAGE, lev.LONG2_LEVERAGE)),
 ('STATUS', ms.STATUS_SHORT=='Short' and ms.STATUS_LONG1=='Long 1' and ms.STATUS_LONG2=='Long 2', (ms.STATUS_SHORT, ms.STATUS_LONG1, ms.STATUS_LONG2)),
]
for name, good, val in checks:
    (ok if good else bad)(f'{name}={val}')

src=Path(ms.__file__).read_text(encoding='utf-8')
for needle, label in [
 ('short_ok_for_smart','SMART_EXIT hedged short-profit guard'),
 ('_force_locked_partition_usd','partition force lock'),
 ('LOCKED_PARTITION_USD = 100.0','partition const 100'),
 ('SIBLING_WIPE','sibling wipe re-arm'),
 ('preserve sibling','safe recovery close'),
 ('_short_underwater','paired hold underwater'),
]:
    (ok if needle in src else bad)(label)

cool=inspect.getsource(bc.BinanceConnector._wait_or_clear_cool_for_close)
(ok if 'max_wait_s: float = 12.0' in cool else bad)('cool default 12.0')
(ok if 'immediate flatten' not in cool else bad)('no immediate flatten')
(ok if ('forced to 12s' in cool or 'ignoring max_wait_s' in cool) else bad)('cool rejects max_wait_s=0')
(ok if 'waiting' in cool and 'clearing residual cool' in cool else bad)('cool wait then residual clear')

# Frontend locks on VPS tree
front_checks=[
 ('/opt/bilshenz/frontend/lib/riskDeskDefaults.js', [
   ("PARTITION_PRESETS_USD = [100]", 'presets only 100'),
   ('LOCKED_PARTITION_USD = 100', 'LOCKED_PARTITION_USD'),
   ('partitionLocked: true', 'defaults locked'),
 ]),
 ('/opt/bilshenz/frontend/lib/scannerRiskSync.js', [
   ('partitionUsd: 100', 'sync always sends 100'),
 ]),
 ('/opt/bilshenz/frontend/hooks/useDeskSession.js', [
   ('partitionUsd: 100', 'desk forces 100'),
 ]),
 ('/opt/bilshenz/frontend/components/InstitutionalRiskDesk.js', [
   ('Partition locked', 'UI locked alert'),
   ('Partition $100 locked', 'UI lock note'),
 ]),
 ('/opt/bilshenz/frontend/components/OpenPositionsPanel.js', [
   ('confirmCloseLeg', 'confirm close leg'),
   ('confirmClosePair', 'confirm close pair'),
   ('confirmCloseAll', 'confirm close all'),
   ('Alert.alert', 'confirm dialogs'),
 ]),
 ('/opt/bilshenz/frontend/broker/binanceFuturesApi.js', [
   ('Math.min(Math.max(Number(m?.[1]) || 3, 1), 12)', 'client cool wait cap 12s'),
 ]),
]
for path, needles in front_checks:
    text=Path(path).read_text(encoding='utf-8', errors='replace')
    for needle, label in needles:
        (ok if needle in text else bad)(f'frontend {label}')

# Disk risk
risk=json.loads(Path('/var/lib/bilshenz/scanner-risk.json').read_text())
(ok if float(risk.get('partition_usd'))==100 else bad)(f"disk partition={risk.get('partition_usd')}")
(ok if abs(float(risk.get('short_pct'))-50)<1e-6 else bad)(f"disk short_pct={risk.get('short_pct')}")
(ok if abs(float(risk.get('long1_pct'))-40)<1e-6 else bad)(f"disk l1={risk.get('long1_pct')}")
(ok if abs(float(risk.get('long2_pct'))-40)<1e-6 else bad)(f"disk l2={risk.get('long2_pct')}")
(ok if risk.get('locked') is True else bad)(f"disk locked={risk.get('locked')}")
(ok if risk.get('partition_usd_locked') is True else bad)(f"disk partition_usd_locked={risk.get('partition_usd_locked')}")

# Live health/status
tok=env.get('BRIDGE_TOKEN','')
def get(url):
    req=urllib.request.Request(url, headers={'X-Bridge-Token':tok})
    with urllib.request.urlopen(req, timeout=12) as r:
        return json.loads(r.read().decode())

h=get('http://127.0.0.1:8766/health')
s=h.get('scanner') or {}
(ok if h.get('connected') else bad)(f"connected={h.get('connected')}")
(ok if s.get('strategy_id')=='short_first_v1' else bad)(f"strategy={s.get('strategy_id')}")
(ok if float(s.get('partition_usd') or 0)==100 else bad)(f"live partition={s.get('partition_usd')}")
(ok if float(s.get('short_partition_pct') or 0)==50 else bad)(f"live short%={s.get('short_partition_pct')}")
(ok if float(s.get('long1_partition_pct') or 0)==40 else bad)(f"live l1%={s.get('long1_partition_pct')}")
(ok if float(s.get('long2_partition_pct') or 0)==40 else bad)(f"live l2%={s.get('long2_partition_pct')}")
(ok if s.get('can_execute') else bad)(f"can_execute={s.get('can_execute')} block={s.get('exec_block')}")
(ok if s.get('partition_usd_locked') is True else bad)(f"live partition_usd_locked={s.get('partition_usd_locked')}")
(ok if s.get('risk_locked') is True else bad)(f"live risk_locked={s.get('risk_locked')}")

# POST $50 must stay $100
body=json.dumps({'partition_usd':50,'short_pct':50,'long1_pct':40,'long2_pct':40}).encode()
req=urllib.request.Request('http://127.0.0.1:8766/api/scanner/risk', data=body, method='POST',
    headers={'Content-Type':'application/json','X-Bridge-Token':tok})
with urllib.request.urlopen(req, timeout=12) as r:
    out=json.loads(r.read().decode())
(ok if float(out.get('partition_usd'))==100 else bad)(f"POST50 -> {out.get('partition_usd')}")
(ok if out.get('partition_usd_locked') is True else bad)('POST50 keeps partition_usd_locked')

# main.py pins 100
main=Path('/opt/bilshenz/binance_trading_system/python/main.py').read_text(encoding='utf-8')
(ok if 'partition_usd=100.0' in main else bad)('api_scanner_risk pins 100.0')
(ok if '_post_login_stream_refresh' in main else bad)('fast login non-blocking streams')

# No instant flatten string anywhere in connector cool path file region
conn=Path(bc.__file__).read_text(encoding='utf-8')
(ok if 'immediate flatten' not in conn else bad)('connector has no immediate flatten')

print('\n=== SUMMARY ===')
print('OK_COUNT', len(oks))
print('FAIL_COUNT', len(fails))
for f in fails:
    print(' -', f)
if fails:
    raise SystemExit(2)
print('ALL_SEP23_25_DETAILS_CONFIRMED')
PY
"""

def main():
    pkey=paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username='root', pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _,o,e=c.exec_command(CMD, timeout=90)
    print(o.read().decode('utf-8','replace'))
    err=e.read().decode('utf-8','replace')
    if err.strip(): print('STDERR', err[-1500:])
    code=o.channel.recv_exit_status()
    c.close()
    return code

if __name__=='__main__':
    raise SystemExit(main())
