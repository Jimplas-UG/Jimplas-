#!/usr/bin/env python3
"""Deep forensic audit: Sep 23-25 baseline vs post-mainnet/testnet return. READ-ONLY."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set +e
export PYTHONUNBUFFERED=1

python3 - <<'PY'
import json, re, gzip, os
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

LOG_DIR = Path('/var/log/bilshenz')
CACHE = Path('/var/lib/bilshenz/trade-history-cache.json')
ENV = Path('/etc/bilshenz.env')
RISK = Path('/var/lib/bilshenz/scanner-risk.json')
SESSION = Path('/var/lib/bilshenz/binance-session.json')

DAYS = [
    '2026-09-23','2026-09-24','2026-09-25',  # baseline
    '2026-09-26','2026-09-27','2026-09-28',
    '2026-09-29','2026-09-30','2026-10-01',  # post-flip window
]

def load_all_logs():
    parts = []
    # uncompressed first
    for name in sorted(LOG_DIR.glob('binance-api.log*')):
        try:
            if name.suffix == '.gz' or str(name).endswith('.gz'):
                with gzip.open(name, 'rt', errors='replace') as f:
                    parts.append(f.read())
            else:
                parts.append(name.read_text(errors='replace'))
            print('LOG_FILE', name, 'bytes', name.stat().st_size)
        except Exception as e:
            print('LOG_READ_FAIL', name, e)
    return '\n'.join(parts)

print('=== ENV / LIVE STATE ===')
env = {}
for line in ENV.read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k,v = line.split('=',1)
        env[k] = v.strip().strip('"').strip("'")
interesting = [
 'BINANCE_TESTNET','BINANCE_FORCE_MAINNET','BINANCE_PAPER','SCANNER_EXEC',
 'FORWARD_DRY_RUN','SCANNER_PARTITION_USD','SCANNER_SMART_EXIT_PCT',
 'SCANNER_SHORT_LEV','SCANNER_LONG_LEV','SCANNER_ENTRY_PCT','SCANNER_SIGNAL_PCT'
]
for k in interesting:
    if k in env:
        val = env[k]
        if 'KEY' in k or 'SECRET' in k or 'TOKEN' in k:
            val = f'len={len(val)}'
        print(f'  {k}={val}')
print('  env_key_len', len(env.get('BINANCE_API_KEY','')), 'secret_len', len(env.get('BINANCE_API_SECRET','')))

if RISK.exists():
    print('RISK', RISK.read_text().strip()[:500])
else:
    print('RISK missing')

if SESSION.exists():
    try:
        sj = json.loads(SESSION.read_text() or '{}')
        print('SESSION keys', list(sj.keys())[:12], 'testnet', sj.get('testnet'), 'key_len', len(str(sj.get('api_key') or sj.get('k') or '')))
    except Exception as e:
        print('SESSION bad', e)

# live health via local curl already done separately — read risk + frozen
import sys
sys.path.insert(0, '/opt/bilshenz/binance_trading_system/python')
from frozen_strategy import assert_frozen_contract, frozen_contract_snapshot as fcs
snap = assert_frozen_contract()
print('CONTRACT', snap['strategy_id'])
print('  entry', snap['entry'])
print('  primary', snap['primary'])
print('  recovery', {k: snap['recovery'][k] for k in ('partition_pct','leverage','adverse1_pct','adverse2_pct','invalidation_pct','pullback_pct','rescue_buffer_pct')})
print('  tp', snap['tp'])
print('  ops', snap.get('ops'))

# SMART_EXIT live module values
import momentum_scanner as ms
import inspect, binance_connector as bc
print('LIVE_MS SMART_EXIT_NET_PCT', getattr(ms, 'SMART_EXIT_NET_PCT', None))
print('LIVE_MS SHORT_TP', getattr(ms, 'SHORT_TP_PCT', None), 'LONG_TP', getattr(ms, 'LONG_TP_PCT', None))
print('LIVE_MS PAIR_INVALIDATION', getattr(ms, 'PAIR_INVALIDATION_PCT', None))
print('LIVE_MS ENTRY', getattr(ms, 'ENTRY_PCT', None), 'SIGNAL', getattr(ms, 'SIGNAL_PCT', None), 'RETRACE', getattr(ms, 'RETRACE_ENTRY_PCT', None))
cool_src = inspect.getsource(bc.BinanceConnector._wait_or_clear_cool_for_close)
print('CLOSE_COOL_DEFAULT_12', 'max_wait_s: float = 12.0' in cool_src)
print('SHORT_OK_GUARD', 'short_ok_for_smart' in open(ms.__file__, encoding='utf-8').read())

print('\n=== LOAD LOGS ===')
text = load_all_logs()
print('LOG_CHARS', len(text))

# Mode / partition / login / force flips
print('\n=== MODE / PARTITION / LOGIN TIMELINE (all days) ===')
pat_events = re.compile(
    r'(FORCE_MAIN|force_main|BINANCE_TESTNET|mode=|login success|login attempt|partition_usd|set_partition|scanner ready|restarting market streams|SWITCH|mainnet|testnet)'
)
# more precise extraction
timeline = []
for ln in text.splitlines():
    day = ln[:10]
    if day not in DAYS and not day.startswith('2026-09') and not day.startswith('2026-10'):
        continue
    if 'login success' in ln:
        m = re.search(r'mode=(\w+).*auto=(\w+)', ln)
        timeline.append((ln[:19], 'LOGIN_OK', m.group(0) if m else ln[-80:]))
    elif 'login attempt' in ln:
        m = re.search(r'testnet=(\w+)', ln)
        timeline.append((ln[:19], 'LOGIN_TRY', f'testnet={m.group(1) if m else "?"}' ))
    elif 'restarting market streams' in ln:
        timeline.append((ln[:19], 'STREAM_RESTART', ln[ln.find('restarting'):][:100]))
    elif 'partition' in ln.lower() and ('usd' in ln.lower() or 'set' in ln.lower() or 'risk' in ln.lower()):
        if any(x in ln for x in ('partition_usd', 'set_partition', 'SCANNER_PARTITION', 'risk update', 'partition=')):
            timeline.append((ln[:19], 'PARTITION', ln[-120:]))
    elif 'FORCE_MAIN' in ln or 'force_main' in ln or 'BINANCE_FORCE_MAINNET' in ln:
        timeline.append((ln[:19], 'FORCE_MAIN', ln[-100:]))
    elif 'scanner ready for execution' in ln:
        timeline.append((ln[:19], 'EXEC_READY', ''))

# dedupe dense
shown = 0
for t in timeline:
    if shown < 120:
        print(t[0], t[1], t[2])
        shown += 1
print('TIMELINE_EVENTS', len(timeline), 'shown', shown)

print('\n=== PER-DAY CLOSE REASONS / ACTIVITY ===')
close_re = re.compile(r'reason=([A-Z0-9_]+)')
short_ok_re = re.compile(r'scanner SHORT (\w+) qty=([0-9.]+) @ ([0-9.]+)')
smart_re = re.compile(r'SMART_EXIT.*?pnl=([-0-9.]+) target=([-0-9.]+)(?:.*?hedges=(\w+).*?short_underwater=(\w+))?')

def day_lines(day):
    return [ln for ln in text.splitlines() if ln.startswith(day)]

summary = {}
for day in DAYS:
    lines = day_lines(day)
    c = Counter()
    smart = []
    shorts = []
    fails = Counter()
    manuals = 0
    cool_fails = 0
    for ln in lines:
        if 'scanner closed' in ln or ('reason=' in ln and ('cooldown' in ln or 'closed' in ln)):
            m = close_re.search(ln)
            if m and 'scanner' in ln:
                c[m.group(1)] += 1
        if 'reason=SMART_EXIT' in ln:
            c['SMART_EXIT_CLOSE'] += 1
        if 'SMART_EXIT' in ln and 'pnl=' in ln:
            c['SMART_EXIT_DECIDE'] += 1
            m = smart_re.search(ln)
            if m:
                smart.append((float(m.group(1)), float(m.group(2)), m.group(3), m.group(4)))
        if 'scanner SHORT ' in ln and 'qty=' in ln and 'failed' not in ln:
            m = short_ok_re.search(ln)
            if m:
                qty, px = float(m.group(2)), float(m.group(3))
                shorts.append((m.group(1), qty*px))
                c['SHORT_OPEN'] += 1
        if 'scanner SHORT failed' in ln:
            c['SHORT_FAIL'] += 1
        if 'EXEC_FAIL' in ln:
            c['EXEC_FAIL'] += 1
            if 'cooling' in ln or '418' in ln:
                cool_fails += 1
                c['EXEC_FAIL_COOL'] += 1
        if 'MANUAL_' in ln or 'manual close' in ln.lower():
            manuals += 1
            c['MANUAL'] += 1
        if 'LONG1' in ln and 'qty=' in ln and 'scanner LONG1' in ln and 'failed' not in ln and 'blocked' not in ln:
            c['LONG1_OPEN'] += 1
        if 'LONG2' in ln and 'qty=' in ln and 'scanner LONG2' in ln and 'failed' not in ln and 'blocked' not in ln:
            c['LONG2_OPEN'] += 1
        if 'INVALIDATION' in ln and 'reason=' in ln:
            c['INVALIDATION'] += 1
        if 'RESCUE' in ln and 'reason=' in ln:
            c['RESCUE'] += 1
        if 'PULLBACK' in ln and 'reason=' in ln:
            c['PULLBACK'] += 1
        if 'SHORT_TP' in ln and 'reason=' in ln:
            c['SHORT_TP'] += 1
        if 'clearing REST cool' in ln or 'clearing residual cool' in ln:
            c['COOL_CLEAR'] += 1
        if 'instant' in ln.lower() and 'clear' in ln.lower():
            c['INSTANT_CLEAR'] += 1
        if 'login success' in ln:
            c['LOGIN_OK'] += 1
            if 'mode=live' in ln or 'mode=mainnet' in ln:
                c['LOGIN_MAINNET'] += 1
            if 'mode=testnet' in ln:
                c['LOGIN_TESTNET'] += 1
    notionals = [n for _,n in shorts]
    summary[day] = {
        'lines': len(lines),
        'counts': dict(c),
        'short_n': len(shorts),
        'avg_short_notional': round(sum(notionals)/len(notionals),2) if notionals else None,
        'smart_avg_pnl': round(sum(p for p,_,_,_ in smart)/len(smart),4) if smart else None,
        'smart_samples': smart[:6],
        'cool_fails': cool_fails,
        'manuals': manuals,
    }
    print(day, 'lines', len(lines), 'shorts', len(shorts), 'avg_notional', summary[day]['avg_short_notional'],
          'cool_fails', cool_fails, 'manuals', manuals)
    print(' ', {k:v for k,v in sorted(c.items()) if v})
    if smart:
        print('  smart', smart[:5], 'avg', summary[day]['smart_avg_pnl'])

print('\n=== TRADE CACHE PnL BY DAY (realized closes) ===')
if CACHE.exists():
    d = json.loads(CACHE.read_text())
    rows = d.get('deals') or []
    by_day = defaultdict(lambda: {'pnl':0.0,'n':0,'wins':0,'losses':0,'gross_win':0.0,'gross_loss':0.0})
    by_day_sym = defaultdict(lambda: defaultdict(float))
    worst = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        pnl = r.get('profit', r.get('realized_pnl', r.get('realizedPnl')))
        try:
            pnl = float(pnl)
        except Exception:
            continue
        t = r.get('time') or 0
        try:
            t = int(t)
        except Exception:
            continue
        if t and t < 1e12:
            t *= 1000
        if not t:
            continue
        day = datetime.fromtimestamp(t/1000, timezone.utc).strftime('%Y-%m-%d')
        if day < '2026-09-23':
            continue
        # count close-like events
        is_close = bool(r.get('is_close') or r.get('isClose'))
        if not is_close and abs(pnl) < 1e-12:
            continue
        bucket = by_day[day]
        bucket['pnl'] += pnl
        bucket['n'] += 1
        if pnl > 0:
            bucket['wins'] += 1
            bucket['gross_win'] += pnl
        elif pnl < 0:
            bucket['losses'] += 1
            bucket['gross_loss'] += pnl
        by_day_sym[day][r.get('symbol')] += pnl
        worst.append((pnl, day, r.get('symbol'), r.get('type'), r.get('position_side'), t, is_close))
    for day in DAYS:
        b = by_day[day]
        print(day, 'n', b['n'], 'pnl', round(b['pnl'],2), 'W/L', f"{b['wins']}/{b['losses']}",
              'grossW', round(b['gross_win'],2), 'grossL', round(b['gross_loss'],2))
        if by_day_sym[day]:
            top = sorted(by_day_sym[day].items(), key=lambda kv: kv[1])[:5]
            print('  worst_syms', [(s, round(v,2)) for s,v in top])
    print('WORST15 overall since 09-23')
    for pnl, day, sym, typ, ps, t, ic in sorted(worst, key=lambda x: x[0])[:15]:
        ts = datetime.fromtimestamp(t/1000, timezone.utc).isoformat()
        print(f'  {ts} {sym} {typ}/{ps} pnl={pnl:.2f} close={ic}')
else:
    print('NO_CACHE')

print('\n=== BASELINE vs RECENT CLOSE MIX ===')
base_days = ['2026-09-23','2026-09-24','2026-09-25']
recent_days = ['2026-09-29','2026-09-30','2026-10-01']
def mix(days):
    tot = Counter()
    for d in days:
        tot.update(summary[d]['counts'])
    return tot
bm, rm = mix(base_days), mix(recent_days)
keys = sorted(set(bm) | set(rm))
print(f"{'metric':30} {'baseline_23-25':>14} {'recent_29-01':>14}")
for k in keys:
    print(f'{k:30} {bm.get(k,0):14} {rm.get(k,0):14}')

print('\n=== INSTANT-CLOSE / COOL DAMAGE WINDOW ===')
# look for clear-and-go / max_wait 0 era markers if any remain in logs
for needle in ['immediate flatten', 'clearing REST cool', 'brief wait', 'waiting', 'max_wait_s', 'instant']:
    n = sum(1 for ln in text.splitlines() if needle in ln and ('2026-09-2' in ln or '2026-09-3' in ln or '2026-10-01' in ln))
    print(needle, n)

print('\n=== DONE ===')
PY

echo '=== LIVE HEALTH / ACCOUNT ==='
TOKEN=$(python3 -c "from pathlib import Path; d={};
[d.__setitem__(a,b.strip().strip(chr(34)).strip(chr(39))) for a,b in (l.split('=',1) for l in Path('/etc/bilshenz.env').read_text().splitlines() if '=' in l and not l.startswith('#'))];
print(d.get('BRIDGE_TOKEN',''))")
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/status > /tmp/st.json
curl -sS --max-time 15 -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/trade-calendar?days=14' > /tmp/cal.json
python3 - <<'PY'
import json
h=json.load(open('/tmp/h.json'))
s=h.get('scanner') or {}
print('health mode', h.get('mode'), 'connected', h.get('connected'), 'cool', h.get('rest_cool_s'))
print('strategy', s.get('strategy_id'), 'partition', s.get('partition_usd'), 'exec', s.get('can_execute'), 'block', s.get('exec_block'))
print('pct', s.get('short_partition_pct'), s.get('long1_partition_pct'), s.get('long2_partition_pct'))
st=json.load(open('/tmp/st.json'))
acct=st.get('account') or {}
print('status mode', st.get('mode'), 'testnet', st.get('testnet'))
print('acct', {k:acct.get(k) for k in ('balance','equity','margin','margin_free','profit','currency','server')})
cal=json.load(open('/tmp/cal.json'))
print('calendar total', cal.get('total_pnl'))
for row in cal.get('days') or []:
    print(row)
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=300)
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    print(out)
    if err.strip():
        print("STDERR", err[-2000:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
