#!/usr/bin/env python3
"""Hard audit: FRA live knobs + frozen_contract + recent trade drift vs Sep23-25."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=40, look_for_keys=False, allow_agent=False)

CMD = r'''
set -e
PY=/opt/bilshenz/binance_trading_system/python/.venv/bin/python
cd /opt/bilshenz/binance_trading_system/python

echo '=== FROZEN CONTRACT ASSERT ==='
$PY - <<'PY'
import traceback
try:
    from frozen_strategy import assert_frozen_contract, frozen_contract_snapshot
    snap = assert_frozen_contract()
    print('CONTRACT_OK', snap['strategy_id'], snap['ops'])
except Exception as e:
    print('CONTRACT_FAIL', e)
    traceback.print_exc()
PY

echo '=== LIVE MODULE KNOBS ==='
$PY - <<'PY'
import momentum_scanner as ms
import leverage_policy as lev
keys = [
 'GAIN_THRESHOLD_PCT','RETRACE_ENTRY_PCT','LONG1_ADVERSE_PCT','LONG2_ADVERSE_PCT',
 'SHORT_TP_PCT','LONG_TP_PCT','LONG_HEDGE_PULLBACK_PCT','SHORT_TRAIL_PULLBACK_PCT',
 'PAIR_INVALIDATION_PCT','HEDGE_RESCUE_BUFFER_PCT','SMART_EXIT_NET_PCT',
 'SHORT_PARTITION_PCT','LONG1_PARTITION_PCT','LONG2_PARTITION_PCT',
 'LOCKED_PARTITION_USD','DEFAULT_PARTITION_USD','STATUS_SHORT','STATUS_LONG1','STATUS_LONG2'
]
for k in keys:
    print(f'{k}={getattr(ms,k,None)!r}')
print('SHORT_LEV', lev.SHORT_LEVERAGE, 'L1', lev.LONG1_LEVERAGE, 'L2', lev.LONG2_LEVERAGE)
# env overrides that can raise floors
import os
for k in sorted(os.environ):
    if k.startswith('SCANNER_') or k.startswith('SHORT_') or k.startswith('LONG_') or 'PARTITION' in k or 'SMART' in k or 'PULLBACK' in k:
        print('ENV', k, '=', os.environ[k])
PY

echo '=== HEALTH / RISK ==='
curl -sS -m 8 http://127.0.0.1:8766/health > /tmp/h.json
$PY - <<'PY'
import json
h=json.load(open('/tmp/h.json'))
sc=h.get('scanner') or {}
want = {
 'partition_usd':100.0,
 'short_partition_pct':50.0,
 'long1_partition_pct':40.0,
 'long2_partition_pct':40.0,
 'short_tp_pct':2.5,
 'long_tp_pct':2.5,
 'long_pullback_pct':0.5,
 'short_pullback_pct':1.5,
}
print('mode', h.get('mode'), 'connected', h.get('connected'))
print('can_execute', sc.get('can_execute'), 'block', sc.get('exec_block'), 'halted', sc.get('user_exec_halted'))
print('strategy', sc.get('strategy_id'), sc.get('strategy_name'))
print('active', sc.get('active_symbol'), 'last_err', sc.get('last_exec_error'))
print('auth', sc.get('api_auth'))
for k,v in want.items():
    got=sc.get(k)
    ok = (got is not None and abs(float(got)-float(v))<1e-6) if isinstance(v,float) else got==v
    print(('OK' if ok else 'DRIFT'), k, 'live=', got, 'want=', v)
# dump extra scanner keys that look like knobs
for k in sorted(sc):
    if any(x in k for x in ('pct','partition','pull','tp','sl','smart','invalid','rescue','gain','retrace','adverse','lev','trail','min_','max_')):
        print('KNOB', k, '=', sc.get(k))
risk=json.load(open('/var/lib/bilshenz/scanner-risk.json')) if __import__('os').path.exists('/var/lib/bilshenz/scanner-risk.json') else {}
print('RISK_FILE', {k:risk.get(k) for k in ('partition_usd','short_pct','long1_pct','long2_pct','exec_halted','locked')})
PY

echo '=== ENV FLAGS ==='
grep -E '^(BINANCE_TESTNET|BINANCE_FORCE_|BINANCE_PAPER|SCANNER_EXEC|FORWARD_DRY_RUN|SCANNER_|SMART_|PARTITION)' /etc/bilshenz.env | sed 's/BINANCE_API_.*/BINANCE_API_***/; s/SECRET=.*/SECRET=***/'

echo '=== RECENT EXITS / HEDGE MISSES (48h) ==='
grep -E 'scanner (SHORT|LONG1|LONG2) |LONG1 failed|LONG2 failed|insufficient_margin|INVALIDATION|SMART_EXIT|LONG1_PULLBACK|LONG2_PULLBACK|PAIRED|orphan|SIBLING|closed leg|closed .* reason=' /var/log/bilshenz/binance-api.log | tail -n 80

echo '=== CODE HASH vs expected markers ==='
$PY - <<'PY'
from pathlib import Path
import hashlib, inspect
import binance_connector as bc
import momentum_scanner as ms
cool = inspect.getsource(bc.BinanceConnector._wait_or_clear_cool_for_close)
print('cool_default_12', 'max_wait_s: float = 12.0' in cool)
print('cool_no_immediate', 'immediate flatten' not in cool)
print('forced_12', 'forced to 12s' in cool or 'ignoring max_wait_s' in cool)
src = Path(ms.__file__).read_text(encoding='utf-8')
for marker in ['short_ok_for_smart','SIBLING_WIPE','force_locked_partition_usd','_force_locked_partition_usd','PAIRED','_short_underwater','LONG1_ADVERSE_PCT']:
    print('marker', marker, marker in src or marker.replace('_force','force') in src)
print('ms_sha', hashlib.sha256(src.encode()).hexdigest()[:16])
print('frozen_sha', hashlib.sha256(Path('frozen_strategy.py').read_text(encoding='utf-8').encode()).hexdigest()[:16])
PY
'''

_, o, e = c.exec_command(CMD, timeout=90)
out = o.read().decode("utf-8", "replace")
Path(__file__).with_name("_sep23-audit-out.txt").write_text(out, encoding="utf-8")
print(out.encode("ascii", "replace").decode("ascii")[:16000])
err = e.read().decode("utf-8", "replace")
if err.strip():
    print("STDERR:", err.encode("ascii", "replace").decode("ascii")[-2500:])
c.close()
