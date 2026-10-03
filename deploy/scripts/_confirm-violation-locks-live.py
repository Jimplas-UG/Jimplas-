#!/usr/bin/env python3
"""Confirm the three violation locks are live and non-regressable on FRA."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=40, look_for_keys=False, allow_agent=False)

CMD = r'''
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
import inspect, json, urllib.request
import momentum_scanner as ms
from frozen_strategy import assert_frozen_contract
from leverage_policy import symbol_exchange_leverage
from momentum_scanner import (
    CoinStrategy, LegPosition, MAGIC_SHORT, LONG1_ADVERSE_PCT, PAIR_INVALIDATION_PCT, SHORT_LEVERAGE, STATUS_SHORT,
)

fails=[]
def ok(m): print('PASS', m)
def bad(m): fails.append(m); print('FAIL', m)

# 1) Contract
try:
    snap=assert_frozen_contract()
    ok(f"assert_frozen_contract {snap['strategy_id']}")
    ok(f"paired_hold_after_hedge_episode={snap['recovery'].get('paired_hold_after_hedge_episode')}")
    ok(f"naked_short_exchange_leverage={snap['recovery'].get('naked_short_exchange_leverage')}")
except AssertionError as e:
    bad(f"contract {e}")

# 2) Naked 10x impossible in manage
manage=inspect.getsource(ms.MomentumScanner._manage_positions)
(ok if 'target = LONG1_LEVERAGE' not in manage else bad)('manage has no naked->10x force')
(ok if 'symbol_exchange_leverage(has_recovery_long=has_long)' in manage else bad)('manage uses symbol_exchange_leverage')
(ok if symbol_exchange_leverage(has_recovery_long=False)==5 else bad)('naked target 5x')
(ok if symbol_exchange_leverage(has_recovery_long=True)==10 else bad)('hedged target 10x')

# 3) Hedge-episode solo exit blocked (behavioral)
from types import SimpleNamespace
conn=SimpleNamespace(cfg=SimpleNamespace(paper=True, api_key=''), _connected=True, ensure_exchange_leverage=lambda *a,**k: True)
sc=ms.MomentumScanner(conn, lambda: True)
coin=CoinStrategy(symbol='LOCKUSDT')
coin.short=LegPosition('SELL', 100.0, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, 97.5)
coin.status=STATUS_SHORT
coin.price=99.0
coin.short_adverse_peak_pct=LONG1_ADVERSE_PCT
(ok if sc._solo_hedge_exit_allowed(coin) is False else bad)('solo exit blocked after +2% episode')
coin2=CoinStrategy(symbol='LOCK2USDT')
coin2.short=LegPosition('SELL', 100.0, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, 97.5)
coin2.price=99.0
coin2.long1=LegPosition('BUY', 102.0, 1.0, 10, 88002, None)
(ok if sc._solo_hedge_exit_allowed(coin2) is False else bad)('solo exit blocked while L1 live')

# 4) No hedge at/past invalidation
coin3=CoinStrategy(symbol='INVUSDT')
coin3.short=LegPosition('SELL', 100.0, 1.0, SHORT_LEVERAGE, MAGIC_SHORT, 97.5)
coin3.price=100*(1+PAIR_INVALIDATION_PCT/100)
sc._exchange_has_short=lambda s: True
sc._exchange_long_covers_recovery=lambda *a,**k: False
sc._short_settle_elapsed=lambda c: True
sc._long1_settle_elapsed=lambda c: True
(ok if sc._long1_entry_allowed(coin3) is False else bad)('L1 blocked at invalidation')
coin3.long1_was_closed=True
(ok if sc._long2_entry_allowed(coin3) is False else bad)('L2 blocked at invalidation')

# 5) Adopt no-overlap markers
adopt=inspect.getsource(ms.MomentumScanner._adopt_exchange_short)
(ok if 'already' in adopt and 'SHORT_LEVERAGE' in adopt else bad)('adopt refreshes in place + 5x')
(ok if 'no overlap' in adopt else bad)('adopt overlap guard string')

# 6) Unit suite
import subprocess, sys
r=subprocess.run([sys.executable,'test_violation_locks.py'], cwd='/opt/bilshenz/binance_trading_system/python', capture_output=True, text=True)
(ok if r.returncode==0 else bad)(f'test_violation_locks rc={r.returncode}')
if r.returncode!=0:
    print(r.stdout[-500:]); print(r.stderr[-500:])

# 7) Live health
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
scst=h.get('scanner') or {}
(ok if h.get('connected') else bad)(f"connected={h.get('connected')}")
(ok if scst.get('can_execute') else bad)(f"can_execute={scst.get('can_execute')} block={scst.get('exec_block')}")
(ok if scst.get('strategy_id')=='short_first_v1' else bad)(f"strategy={scst.get('strategy_id')}")
(ok if abs(float(scst.get('partition_usd') or 0)-100)<1e-9 else bad)(f"partition={scst.get('partition_usd')}")

print('\n=== CONFIRM ===')
print('FAIL_COUNT', len(fails))
for f in fails: print(' -', f)
print('STATUS', 'LOCKED_NOT_BREAKING' if not fails else 'REGRESSION')
raise SystemExit(2 if fails else 0)
PY
'''
_, o, e = c.exec_command(CMD, timeout=60)
out = o.read().decode("utf-8", "replace")
print(out.encode("ascii", "replace").decode("ascii"))
err = e.read().decode("utf-8", "replace")
if err.strip():
    print("STDERR", err.encode("ascii", "replace").decode("ascii")[-800:])
print("EXIT", o.channel.recv_exit_status())
c.close()
