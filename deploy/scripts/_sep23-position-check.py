#!/usr/bin/env python3
"""Compare live FRA to Sep 23-25 frozen desk contract."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=40, look_for_keys=False, allow_agent=False)

CMD = r'''
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
import json, urllib.request, inspect
from frozen_strategy import (
    assert_frozen_contract, LOCKED_PARTITION_USD, SMART_EXIT_NET_PCT,
    CLOSE_REST_COOL_MAX_WAIT_S, LONG1_ADVERSE_PCT, LONG2_ADVERSE_PCT,
    PAIR_INVALIDATION_PCT, PRIMARY_LEVERAGE, RECOVERY_LEVERAGE,
    PRIMARY_PARTITION_PCT, RECOVERY_PARTITION_PCT,
)
import momentum_scanner as ms
import binance_connector as bc
from leverage_policy import symbol_exchange_leverage

tok = open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
snap = assert_frozen_contract()
h = json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc = h.get('scanner') or {}
st = json.loads(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8766/api/status', headers={'Authorization': 'Bearer ' + tok}), timeout=12).read())
pos = json.loads(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={'Authorization': 'Bearer ' + tok}), timeout=12).read())

rows = []
def add(name, ok, detail=''):
    rows.append((bool(ok), name, detail))
    print(('MATCH' if ok else 'DRIFT'), name, detail)

add('strategy short_first_v1', snap['strategy_id'] == 'short_first_v1', snap['strategy_id'])
add('partition $100', float(sc.get('partition_usd') or 0) == LOCKED_PARTITION_USD, str(sc.get('partition_usd')))
add('partition locked', snap['ops']['partition_usd_locked'] is True)
add('short 5x / long 10x', symbol_exchange_leverage(has_recovery_long=False) == 5 and symbol_exchange_leverage(has_recovery_long=True) == 10)
add('50/40/40', abs(ms.SHORT_PARTITION_PCT - 50) < 1e-6 and abs(ms.LONG1_PARTITION_PCT - 40) < 1e-6 and abs(ms.LONG2_PARTITION_PCT - 40) < 1e-6)
add('L1 +2% / L2 +4% / inv 6.5%', abs(ms.LONG1_ADVERSE_PCT - 2) < 1e-9 and abs(ms.LONG2_ADVERSE_PCT - 4) < 1e-9 and abs(ms.PAIR_INVALIDATION_PCT - 6.5) < 1e-9)
add('SMART_EXIT 6% + short profit if hedged', abs(float(snap['ops']['smart_exit_net_pct']) - 6) < 1e-9 and snap['ops']['smart_exit_requires_short_profit_if_hedged'] is True)
add('REST cool 12s (no instant flatten)', abs(float(snap['ops']['close_rest_cool_max_wait_s']) - 12) < 1e-9)
add('manual close confirm', snap['ops']['manual_close_confirm_required'] is True)
add('paired hold after hedge episode', snap['recovery'].get('paired_hold_after_hedge_episode') is True)
add('naked short never force 10x', 'target = LONG1_LEVERAGE' not in inspect.getsource(ms.MomentumScanner._manage_positions))
add('rule kernel + close chunk/abort', hasattr(ms.MomentumScanner, '_rule_watchdog') and 'long_residual_abort_short' in inspect.getsource(bc.BinanceConnector.close_position))
add('book flat', len(pos.get('positions') or []) == 0, str(len(pos.get('positions') or [])))
add('connected', bool(h.get('connected')))

print('---')
print('exec_halted', sc.get('user_exec_halted'), '(intentional after PORTAL — not a Sep23 rule drift)')
print('can_execute', sc.get('can_execute'), 'block', sc.get('exec_block'))
print('mode', 'testnet' if st.get('testnet') else 'mainnet', 'balance', (st.get('account') or {}).get('balance'))
drift = [n for ok, n, _ in rows if not ok]
print('SEP23_25_CONTRACT', 'ALIGNED' if not drift else 'NOT_ALIGNED')
print('DRIFTS', drift or 'none')
PY
'''
_, o, e = c.exec_command(CMD, timeout=60)
print(o.read().decode('utf-8', 'replace').encode('ascii', 'replace').decode('ascii'))
c.close()
