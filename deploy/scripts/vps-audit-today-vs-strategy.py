#!/usr/bin/env python3
"""Deep audit: today's trades vs frozen short_first_v1 criteria. Read-only."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set +e
cd /opt/bilshenz/binance_trading_system/python
DAY=$(date -u +%Y-%m-%d)
echo "UTC_DAY=$DAY"

echo '=== FROZEN CONTRACT LIVE ==='
python3 - <<'PY'
from frozen_strategy import assert_frozen_contract
snap=assert_frozen_contract()
print('OK', snap['strategy_id'])
print('entry', snap['entry'])
print('primary', snap['primary'])
print('recovery', {k:snap['recovery'][k] for k in ('partition_pct','leverage','adverse1_pct','adverse2_pct','invalidation_pct','pullback_pct','rescue_buffer_pct')})
print('tp', snap['tp'])
PY

TOKEN=$(python3 -c "from pathlib import Path; d={};
[d.__setitem__(a,b.strip().strip(chr(34)).strip(chr(39))) for a,b in (l.split('=',1) for l in Path('/etc/bilshenz.env').read_text().splitlines() if '=' in l and not l.startswith('#'))];
print(d.get('BRIDGE_TOKEN',''))")

echo '=== LIVE RISK / MODE ==='
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json
python3 - <<'PY'
import json
h=json.load(open('/tmp/h.json'))
s=h.get('scanner') or {}
print('mode', h.get('mode'), 'connected', h.get('connected'))
print('strategy', s.get('strategy_id'), 'partition_usd', s.get('partition_usd'))
print('pct', s.get('short_partition_pct'), s.get('long1_partition_pct'), s.get('long2_partition_pct'))
print('exec', s.get('can_execute'), 'block', s.get('exec_block'), 'halted', s.get('user_exec_halted'))
print('risk_file', open('/var/lib/bilshenz/scanner-risk.json').read().strip())
PY

echo '=== TODAY LOG: OPENS / CLOSES / FAILS / HEDGES ==='
grep "$DAY" /var/log/bilshenz/binance-api.log | grep -E 'scanner SHORT |scanner LONG|EXEC_OK|EXEC_FAIL|scanner closed|entry cooldown|LONG1|LONG2|PULLBACK|INVALIDATION|RESCUE|MANUAL_|adverse|retrace|GAIN|partition=|SIBLING|adopt|blocked' | grep -v 'positions: Binance REST' | grep -v 'margin cache' | tail -n 200

echo '=== STRUCTURED PARSE TODAY ==='
python3 - <<'PY'
import re, json
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime, timezone

day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
lines = [ln for ln in Path('/var/log/bilshenz/binance-api.log').read_text(errors='replace').splitlines() if day in ln]

opens=[]
longs=[]
closes=[]
fails=[]
cooldowns=[]
blocks=[]

for ln in lines:
    if 'scanner SHORT ' in ln and 'qty=' in ln and 'failed' not in ln:
        m=re.search(r'scanner SHORT (\w+) qty=([0-9.]+) @ ([0-9.]+) order=(\w+).*latency_ms=([0-9.]+)', ln)
        if m:
            opens.append({'t':ln[:19],'sym':m.group(1),'qty':float(m.group(2)),'px':float(m.group(3)),'order':m.group(4),'lat':float(m.group(5)),'raw':ln})
    if re.search(r'scanner LONG[12] ', ln) and 'qty=' in ln and 'failed' not in ln and 'blocked' not in ln:
        m=re.search(r'scanner (LONG[12]) (\w+) qty=([0-9.]+) @ ([0-9.]+)', ln)
        if m:
            longs.append({'t':ln[:19],'leg':m.group(1),'sym':m.group(2),'qty':float(m.group(3)),'px':float(m.group(4)),'raw':ln})
    if 'scanner closed' in ln:
        m=re.search(r'scanner closed(?: leg)? (\w+).*reason=([A-Z0-9_]+)', ln)
        if m:
            closes.append({'t':ln[:19],'sym':m.group(1),'reason':m.group(2),'raw':ln})
        else:
            m2=re.search(r'reason=([A-Z0-9_]+)', ln)
            closes.append({'t':ln[:19],'sym':'?','reason':m2.group(1) if m2 else '?','raw':ln})
    if 'scanner SHORT failed' in ln or ('EXEC_FAIL' in ln and 'SELL' in ln):
        fails.append(ln[:220])
    if 'entry cooldown' in ln:
        m=re.search(r'cooldown (\w+) for (\d+)s reason=([A-Z0-9_]+)', ln)
        if m:
            cooldowns.append({'t':ln[:19],'sym':m.group(1),'sec':m.group(2),'reason':m.group(3)})
    if 'blocked' in ln.lower() and 'scanner' in ln:
        blocks.append(ln[:220])
    if 'LONG1' in ln and ('adverse' in ln.lower() or 'opened' in ln.lower() or 'qty=' in ln):
        pass

print('OPENS', len(opens))
for o in opens:
    print(' OPEN', o['t'], o['sym'], 'qty', o['qty'], '@', o['px'], 'lat', o['lat'])
print('LONGS', len(longs))
for o in longs:
    print(' HEDGE', o['t'], o['leg'], o['sym'], 'qty', o['qty'], '@', o['px'])
print('CLOSES', len(closes))
for o in closes:
    print(' CLOSE', o['t'], o['sym'], o['reason'])
print('COOLDOWNS', cooldowns)
print('FAIL_COUNT', len(fails))
for f in fails[-15:]:
    print(' FAIL', f)
print('BLOCK_COUNT', len(blocks))
for b in blocks[-10:]:
    print(' BLOCK', b)

# Expected short notional ~ partition*0.5*5 = 100*0.5*5 = 250 USDT
# qty * price ~= notional
print('--- SIZING CHECK (expect ~$250 short notional at $100 partition 50% 5x) ---')
for o in opens:
    notional = o['qty'] * o['px']
    print(o['sym'], 'notional', round(notional,2), 'vs_target_250', round(notional-250,2), 'pct_err', round((notional-250)/250*100,1) if 250 else None)
PY

echo '=== DEAL CACHE TODAY ==='
python3 - <<'PY'
import json
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict

day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
start = datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0).timestamp()*1000
p=Path('/var/lib/bilshenz/trade-history-cache.json')
d=json.loads(p.read_text())
rows=d.get('deals') or []
today=[]
for r in rows:
    t=int(r.get('time') or 0)
    if t and t<1e12: t*=1000
    if t < start: continue
    today.append(r)
print('deals_today', len(today))
by_sym=defaultdict(list)
for r in today:
    by_sym[r.get('symbol')].append(r)
for sym, rs in sorted(by_sym.items()):
    print('==', sym, 'fills', len(rs))
    for r in sorted(rs, key=lambda x: int(x.get('time') or 0)):
        t=int(r.get('time') or 0)
        ts=datetime.fromtimestamp(t/1000, timezone.utc).isoformat()
        print(ts, r.get('type'), r.get('position_side'), 'vol', r.get('volume'), '@', r.get('price'), 'pnl', r.get('profit') or r.get('realized_pnl'), 'close', r.get('is_close'), 'lev?', r.get('leverage'))
PY

echo '=== CALENDAR TODAY ==='
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/trade-calendar?days=2' | python3 -c "import sys,json;d=json.load(sys.stdin);print(d)"

echo '=== OPEN POSITIONS NOW + VALIDATE ==='
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions > /tmp/pos.json
python3 - <<'PY'
import json
d=json.load(open('/tmp/pos.json'))
rows=d if isinstance(d,list) else d.get('positions') or []
print('open', len(rows))
for r in rows:
    print(r)
PY

# scanner status for active strategies
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/scanner/snapshot > /tmp/snap.json
python3 - <<'PY'
import json
from collections import Counter
d=json.load(open('/tmp/snap.json'))
rows=d.get('rows') or []
print('status', dict(Counter(str(r.get('status')) for r in rows)))
for st in ('Short','Long 1','Long 2','Pending','Watching','Sending'):
    for r in rows:
        if str(r.get('status'))==st:
            print(st, r.get('symbol'), {k:r.get(k) for k in ('pctGain','pct15m','retracePct','price','highestPrice','unrealizedPnl','direction')})
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=150)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR:", err[-1500:])
    c.close()

if __name__ == "__main__":
    main()
