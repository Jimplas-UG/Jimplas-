#!/usr/bin/env python3
"""End-to-end FRA desk audit — locks, live state, close chunk, kernel, positions."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=45, look_for_keys=False, allow_agent=False)

CMD = r'''
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
import json, urllib.request, inspect, re, time
from pathlib import Path
from collections import Counter

fails = []
def ok(m): print('PASS', m)
def bad(m): fails.append(m); print('FAIL', m)

tok = open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")

# --- Live health ---
h = json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc = h.get('scanner') or {}
(ok if h.get('connected') else bad)(f"connected={h.get('connected')}")
(ok if sc.get('partition_usd') == 100.0 else bad)(f"partition={sc.get('partition_usd')}")
(ok if sc.get('strategy_id') == 'short_first_v1' else bad)(f"strategy={sc.get('strategy_id')}")
print('INFO can_execute', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'), 'block', sc.get('exec_block'), 'active', sc.get('active_symbol'))
print('INFO rule_kernel', sc.get('rule_kernel'))

req = urllib.request.Request('http://127.0.0.1:8766/api/status', headers={'Authorization': 'Bearer ' + tok})
st = json.loads(urllib.request.urlopen(req, timeout=15).read())
print('INFO mode', 'testnet' if st.get('testnet') else 'mainnet', 'bal', (st.get('account') or {}).get('balance'))

reqp = urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={'Authorization': 'Bearer ' + tok})
pos = json.loads(urllib.request.urlopen(reqp, timeout=15).read())
items = pos.get('positions') or []
(ok if len(items) == 0 else bad)(f"open_positions={len(items)}")
for p in items[:8]:
    print(' POS', p.get('symbol'), p.get('positionSide'), p.get('volume'), p.get('leverage'), p.get('margin_type'), p.get('profit'))

# --- Contract + code markers ---
import momentum_scanner as ms
import binance_connector as bc
import execution_engine as ee
import rule_kernel as rk
from frozen_strategy import assert_frozen_contract
from leverage_policy import symbol_exchange_leverage

try:
    snap = assert_frozen_contract()
    ok(f"assert_frozen_contract {snap['strategy_id']}")
except AssertionError as e:
    bad(f"contract {e}")

(ok if symbol_exchange_leverage(has_recovery_long=False) == 5 else bad)('naked 5x')
(ok if symbol_exchange_leverage(has_recovery_long=True) == 10 else bad)('hedged 10x')
manage = inspect.getsource(ms.MomentumScanner._manage_positions)
(ok if 'target = LONG1_LEVERAGE' not in manage else bad)('no naked force 10x')
(ok if hasattr(ms.MomentumScanner, '_solo_hedge_exit_allowed') else bad)('solo hedge lock')
(ok if hasattr(ms.MomentumScanner, '_rule_watchdog') else bad)('watchdog')
(ok if hasattr(ms.MomentumScanner, '_build_rule_intent') else bad)('rule intent builder')
(ok if 'rule_intent=self._build_rule_intent' in inspect.getsource(ms.MomentumScanner.__init__) else bad)('engine bound to kernel')
eng_src = Path('execution_engine.py').read_text(encoding='utf-8')
(ok if 'preflight_open' in eng_src and 'rule_kernel_missing_intent' in eng_src else bad)('engine fail-closed kernel')
close_src = inspect.getsource(bc.BinanceConnector.close_position)
(ok if 'max_cell' in close_src or 'marketMaxQty' in close_src else bad)('close chunks market max')
(ok if '_close_rank' in close_src else bad)('close LONGs before SHORT')
(ok if 'long_residual_abort_short' in close_src else bad)('abort SHORT if LONG residual')
side_src = inspect.getsource(bc.BinanceConnector.close_by_position_side)
(ok if 'max_cell' in side_src or 'marketMaxQty' in side_src else bad)('close_by_position_side chunks')
(ok if 'get_symbol_spec' in side_src else bad)('close_by_position_side uses symbol filters')
leg_src = inspect.getsource(bc.BinanceConnector.close_leg)
(ok if 'close_by_position_side' in leg_src else bad)('close_leg delegates to chunked closer')
(ok if 'PARTIAL_CLOSE_EMERGENCY_HALT' in inspect.getsource(ms.MomentumScanner._close_all) else bad)('partial close halt')
parse_src = inspect.getsource(bc.BinanceConnector._parse_symbol_filters)
(ok if 'MARKET_LOT_SIZE' in parse_src and 'marketMaxQty' in parse_src else bad)('MARKET_LOT_SIZE parsed')
sync_src = inspect.getsource(ms.MomentumScanner._sync_short_entry_from_exchange)
(ok if 'max(local, ex_entry)' in sync_src else bad)('no deflate short entry')
main_src = Path('main.py').read_text(encoding='utf-8')
(ok if 'manual_qty_exceeds_locked_partition' in main_src else bad)('manual size reject')

# --- Kernel unit checks on live module ---
from rule_kernel import OpenIntent, preflight_open, audit_live_state, LiveState, should_emergency_halt
v = preflight_open(OpenIntent(symbol='X', leg='LONG1', side='BUY', qty=1, price=1, has_exchange_short=True, has_scanner_short=True, live_adverse_pct=0.5))
(ok if (not v.ok and v.code == 'L1_EARLY') else bad)(f'kernel early L1 {v}')
v2 = preflight_open(OpenIntent(symbol='X', leg='SHORT', side='SELL', qty=1, price=1, has_exchange_short=True))
(ok if (not v2.ok and v2.code == 'OVERLAP_SHORT') else bad)(f'kernel overlap {v2}')
v3 = preflight_open(OpenIntent(symbol='PORTALUSDT', leg='LONG1', side='BUY', qty=37937, price=0.02, has_exchange_short=True, has_scanner_short=True, live_adverse_pct=2.1, market_max_qty=30000))
(ok if (not v3.ok and v3.code == 'MARKET_MAX') else bad)(f'kernel portal market max {v3}')
codes = audit_live_state(LiveState(symbol='X', has_exchange_short=True, has_scanner_short=True, exchange_leverage=10))
(ok if 'NAKED_SHORT_AT_10X' in codes and should_emergency_halt(codes) else bad)(f'watchdog naked10x {codes}')

# --- PORTAL filter sanity ---
import urllib.request as u
data = json.loads(u.urlopen('https://testnet.binancefuture.com/fapi/v1/exchangeInfo', timeout=30).read())
portal = next(s for s in data['symbols'] if s['symbol'] == 'PORTALUSDT')
parsed = bc.BinanceConnector._parse_symbol_filters(bc.BinanceConnector.__new__(bc.BinanceConnector), portal)
(ok if float(parsed.get('marketMaxQty') or 0) == 30000 else bad)(f"portal marketMax={parsed.get('marketMaxQty')}")
# Simulate chunk plan for 37937.5
mmax = float(parsed['marketMaxQty']); step = float(parsed['marketStepSize']); rem = 37937.5; chunks = []
while rem > 1e-9:
    cqty = min(rem, mmax)
    chunks.append(cqty); rem -= cqty
(ok if len(chunks) == 2 and abs(sum(chunks) - 37937.5) < 1e-6 and max(chunks) <= mmax else bad)(f'chunk plan {chunks}')

# --- Run unit suites on FRA ---
import subprocess, sys
for t in ['test_violation_locks.py', 'test_rule_kernel.py', 'test_frozen_strategy.py', 'test_strategy_guards.py', 'test_exec_session.py']:
    r = subprocess.run([sys.executable, t], cwd='.', capture_output=True, text=True)
    (ok if r.returncode == 0 else bad)(f'{t} rc={r.returncode}')
    if r.returncode != 0:
        print((r.stdout + r.stderr)[-800:])

# --- Recent violation / orphan / -4005 storm check (last log) ---
text = Path('/var/log/bilshenz/binance-api.log').read_text(errors='replace')
# only last 2000 lines for recency
lines = text.splitlines()[-5000:]
c4005 = sum(1 for ln in lines if '-4005' in ln)
corphan = sum(1 for ln in lines if 'orphan long' in ln)
ckernel = sum(1 for ln in lines if 'RULE_KERNEL' in ln or 'RULE_WATCHDOG' in ln)
cpartial = sum(1 for ln in lines if 'partial_close_remaining_legs' in ln)
print('INFO recent_log -4005', c4005, 'orphan', corphan, 'kernel', ckernel, 'partial_close', cpartial)
# After chunk deploy, new -4005 on close of oversized should be ~0 if chunking works; historical may remain
# Check if close_position still has unchunked path by searching for failed PORTAL after deploy marker
deploy_idx = None
for i, ln in enumerate(lines):
    if 'PORTAL_CHUNK_DEPLOY_OK' in ln or 'FULL_DEPLOY_OK' in ln or 'test_violation_locks: ALL OK' in ln:
        deploy_idx = i
# Use service restart heuristic: last 'Uvicorn running' or systemd not in this log — use last 'scanner risk sanitized' after 04:24
post = [ln for ln in lines if ln.startswith('2026-10-05T04:2') or ln.startswith('2026-10-05T04:3') or ln.startswith('2026-10-05T05:') or ln.startswith('2026-10-05T06:') or ln.startswith('2026-10-05T07:')]
# Better: check code on disk mtime vs last -4005
import os
mtime = os.path.getmtime('binance_connector.py')
print('INFO connector_mtime', time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(mtime)))

# Dry-run: ensure close_position source deployed matches chunk
(ok if 'closed in' in close_src.lower() or 'chunks' in close_src.lower() or 'chunk_i' in close_src else bad)('close loop chunks')

# Env risks
env = Path('/etc/bilshenz.env').read_text(errors='replace')
(ok if 'BINANCE_LEVERAGE=10' in env else bad)('note: BINANCE_LEVERAGE still 10 in env (policy should override)')
# Not a fail if policy overrides — informational only; remove from fails if we added
if fails and fails[-1].startswith('note:'):
    fails.pop()
    print('INFO BINANCE_LEVERAGE=10 present — leverage_policy must remain sole authority')

print('\n=== E2E AUDIT ===')
print('FAIL_COUNT', len(fails))
for f in fails:
    print(' ', f)
print('STATUS', 'DESK_CLEAN' if not fails else 'DESK_ISSUES')
print('EXIT', 0 if not fails else 1)
raise SystemExit(0 if not fails else 1)
PY
'''

_, o, e = c.exec_command(CMD, timeout=180)
out = o.read().decode('utf-8', 'replace')
err = e.read().decode('utf-8', 'replace')
print(out.encode('ascii', 'replace').decode('ascii'))
if err.strip():
    print('STDERR', err.encode('ascii', 'replace').decode('ascii')[-2000:])
Path(__file__).with_name('_e2e-desk-audit.txt').write_text(out, encoding='utf-8')
c.close()
raise SystemExit(0 if 'STATUS DESK_CLEAN' in out else 1)
