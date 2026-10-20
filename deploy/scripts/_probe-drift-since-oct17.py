#!/usr/bin/env python3
"""What drifted after Oct16 Sep restore — knobs, env, locks, PnL, rule breaks."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
export PYTHONIOENCODING=utf-8
PY=/opt/bilshenz/binance_trading_system/python/.venv/bin/python
cd /opt/bilshenz/binance_trading_system/python

echo '=== SERVICES ==='
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
date -u +'utc=%Y-%m-%dT%H:%M:%SZ'

echo '=== ENV SCANNER KNOBS ==='
grep -E '^SCANNER_|^LOCKED_|^PARTITION' /etc/bilshenz.env 2>/dev/null || true
echo '=== PROC ENV ==='
pid=$(systemctl show -p MainPID --value bilshenz-binance-api)
tr '\0' '\n' < /proc/$pid/environ 2>/dev/null | grep -E 'SCANNER_|PARTITION|LOCKED' || echo 'none'

echo '=== LIVE CONTRACT DISK ==='
$PY - <<'PY'
from frozen_strategy import (
    STRATEGY_ID, STRATEGY_VARIANT, RETRACE_ENTRY_PCT, GAIN_THRESHOLD_PCT,
    HEDGED_MAX_HOLD_MS, LOCKED_PARTITION_USD, assert_frozen_contract,
)
import momentum_scanner as ms
snap = assert_frozen_contract()
print('FS', STRATEGY_ID, STRATEGY_VARIANT, 'gain', GAIN_THRESHOLD_PCT, 'retrace', RETRACE_ENTRY_PCT,
      'pair_ms', HEDGED_MAX_HOLD_MS, 'part', LOCKED_PARTITION_USD)
print('MS', 'gain', ms.GAIN_THRESHOLD_PCT, 'retrace', ms.RETRACE_ENTRY_PCT,
      'pair_ms', ms.HEDGED_MAX_HOLD_MS, 'part', getattr(ms, 'LOCKED_PARTITION_USD', None))
print('CONTRACT_OK', snap.get('strategy_id'), snap.get('strategy_variant'))
# sep expectation
ok = (
    STRATEGY_VARIANT == 'sep_retrace07'
    and abs(RETRACE_ENTRY_PCT - 0.7) < 1e-9
    and abs(ms.RETRACE_ENTRY_PCT - 0.7) < 1e-9
    and HEDGED_MAX_HOLD_MS == 0
    and ms.HEDGED_MAX_HOLD_MS == 0
)
print('SEP_MATCH', ok)
if not ok:
    print('DRIFT_DETAIL', {
        'variant': STRATEGY_VARIANT,
        'fs_retrace': RETRACE_ENTRY_PCT,
        'ms_retrace': ms.RETRACE_ENTRY_PCT,
        'fs_hold': HEDGED_MAX_HOLD_MS,
        'ms_hold': ms.HEDGED_MAX_HOLD_MS,
    })
PY

echo '=== HEALTH / STATUS ==='
$PY - <<'PY'
import json, time, urllib.request, pathlib, collections, re, calendar
from collections import defaultdict, Counter

tok = open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
H = {'Authorization': 'Bearer ' + tok}

def get(path):
    req = urllib.request.Request('http://127.0.0.1:8766' + path, headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=25).read())

h = json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc = h.get('scanner') or {}
st = get('/api/status')
acc = st.get('account') or {}
pos = get('/api/positions')
opens = [p for p in (pos.get('positions') or []) if abs(float(p.get('volume') or 0)) > 1e-12]
print('bal', acc.get('balance'), 'eq', acc.get('equity'), 'float', acc.get('profit'), 'testnet', st.get('testnet'))
print('can', sc.get('can_execute'), 'block', sc.get('exec_block'), 'halt', sc.get('user_exec_halted'),
      'part', sc.get('partition_usd'), 'tracked', sc.get('symbols_tracked'), 'active', sc.get('active_symbol'))
print('open_n', len(opens))
for p in opens:
    print('OPEN', p.get('symbol'), p.get('positionSide'), 'ui', p.get('leverage'), 'ex', p.get('exchange_leverage'),
          'qty', p.get('volume'), 'pnl', p.get('profit'), 'entry', p.get('price_open'))

# calendar since Oct 16 restore
cal = get('/api/trade-calendar?days=20')
print('CAL total', cal.get('total_pnl'), 'since', cal.get('since'))
for d in cal.get('days') or []:
    if (d.get('date') or '') >= '2026-10-16':
        print('  DAY', d)

# rule break markers since Oct 17
since = '2026-10-17T00:00'
lines = []
with open('/var/log/bilshenz/binance-api.log', errors='replace') as fh:
    for l in fh:
        if l.startswith('2026-') and l[:16] >= since[:16]:
            lines.append(l)
print('LOG_LINES_since_oct17', len(lines))
marks = Counter()
for l in lines:
    if 'EXEC_OK' in l: marks['EXEC_OK'] += 1
    if 'EXEC_FAIL' in l: marks['EXEC_FAIL'] += 1
    if '418 IP ban' in l: marks['418'] += 1
    if 'used weight' in l: marks['weight'] += 1
    if 'positions_unavailable' in l: marks['pos_unavail'] += 1
    if 'close_zero_executed_qty' in l: marks['close_zero'] += 1
    if 'close incomplete' in l: marks['close_incomplete'] += 1
    if 'INVALIDATION' in l and ('adverse' in l or 'reason=INVALIDATION' in l): marks['INVALIDATION'] += 1
    if 'RESCUE' in l and ('EXIT' in l or 'reason=RESCUE' in l or 'flatten' in l.lower()): marks['RESCUE'] += 1
    if 'SHORT_TP' in l and ('reason=SHORT_TP' in l or 'scanner SHORT_TP' in l): marks['SHORT_TP'] += 1
    if 'PAIR_TIME' in l: marks['PAIR_TIME'] += 1
    if 'LONG1' in l and ('scanner LONG1' in l or 'EXEC_OK' in l and 'BUY' in l): marks['LONG1_hit'] += 1
    if 'target = LONG1_LEVERAGE' in l: marks['naked_10x_log'] += 1
    if 'SAFE_MODE' in l or 'rule_kernel' in l: marks['kernel'] += 1
    if 'Remote end closed' in l: marks['remote_closed'] += 1
print('MARKS', dict(marks))

# sample EXEC since 17
print('SAMPLE_EXEC')
for l in [x for x in lines if 'EXEC_OK' in x or 'EXEC_FAIL' in x][-12:]:
    print(' ', l.strip()[:220])

# deals since Oct 17
raw = json.loads(pathlib.Path('/var/lib/bilshenz/trade-history-cache.json').read_text())
deals = raw.get('deals') or []
def ts(d):
    v = float(d.get('time') or 0)
    return int(v if v > 1e12 else v * 1000)
cut = calendar.timegm(time.strptime('2026-10-17', '%Y-%m-%d')) * 1000
recent = [d for d in deals if ts(d) >= cut]
sym_pnl = defaultdict(float)
sym_n = Counter()
day_pnl = defaultdict(float)
for d in recent:
    pnl = float(d.get('realized_pnl') or d.get('profit') or 0)
    if d.get('is_close') or abs(pnl) > 1e-12:
        sym = str(d.get('symbol') or '?')
        sym_pnl[sym] += pnl
        if d.get('is_close'):
            sym_n[sym] += 1
        day = time.strftime('%Y-%m-%d', time.gmtime(ts(d)/1000))
        day_pnl[day] += pnl
print('DEALS_since_oct17', len(recent), 'net', round(sum(sym_pnl.values()), 2))
print('DEAL_BY_DAY', {k: round(v, 2) for k, v in sorted(day_pnl.items())})
print('WORST', [(s, round(p, 2), sym_n[s]) for s, p in sorted(sym_pnl.items(), key=lambda kv: kv[1])[:10]])

# live open book rule check
print('=== OPEN BOOK RULES ===')
by = defaultdict(list)
for p in opens:
    by[str(p.get('symbol') or '')].append(p)
breaks = []
for sym, legs in by.items():
    shorts = [p for p in legs if str(p.get('positionSide') or '').upper() == 'SHORT' or str(p.get('type') or '').upper() == 'SELL']
    longs = [p for p in legs if str(p.get('positionSide') or '').upper() == 'LONG' or str(p.get('type') or '').upper() == 'BUY']
    for s in shorts:
        ui = int(float(s.get('leverage') or 0))
        ex = int(float(s.get('exchange_leverage') or 0))
        if not longs and ex == 10:
            breaks.append(f'NAKED_SHORT_10x {sym} ui={ui} ex={ex}')
        if longs and ui != 5:
            breaks.append(f'HEDGED_SHORT_UI_NOT_5 {sym} ui={ui}')
        # sizing
        entry = float(s.get('price_open') or 0)
        qty = float(s.get('volume') or 0)
        notional = entry * qty
        if entry > 0 and notional > 250 * 1.35:
            breaks.append(f'SHORT_OVERSIZE {sym} notional={notional:.1f}')
    for lg in longs:
        if not shorts:
            breaks.append(f'ORPHAN_LONG {sym}')
        entry = float(lg.get('price_open') or 0)
        qty = float(lg.get('volume') or 0)
        notional = entry * qty
        if entry > 0 and notional > 400 * 1.35:
            breaks.append(f'LONG_OVERSIZE {sym} notional={notional:.1f}')
print('LIVE_BREAKS', breaks or 'none')

# file mtimes vs restore
import os, subprocess
print('=== CODE MTIMES ===')
for f in ['frozen_strategy.py', 'momentum_scanner.py', 'binance_connector.py', 'main.py']:
    stt = os.stat(f)
    print(f, time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime(stt.st_mtime)))
print('HEAD', subprocess.getoutput('cd /opt/bilshenz && git log -1 --oneline 2>/dev/null || echo no_git'))
# verify string markers
src = open('frozen_strategy.py').read()
print('variant_in_file', 'sep_retrace07' in src, 'r5_pairtime' in src)
print('retrace_line', [l.strip() for l in src.splitlines() if l.strip().startswith('RETRACE_ENTRY_PCT')])
print('hold_line', [l.strip() for l in src.splitlines() if 'HEDGED_MAX_HOLD_MS' in l and '=' in l and not l.strip().startswith('#')])
msrc = open('momentum_scanner.py').read()
print('ms_retrace_default', [l.strip() for l in msrc.splitlines() if 'SCANNER_RETRACE_PCT' in l][:2])
print('ms_hold_default', [l.strip() for l in msrc.splitlines() if 'SCANNER_HEDGED_MAX_HOLD_MS' in l][:2])
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=180)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-2000:])
    c.close()

if __name__ == "__main__":
    main()
