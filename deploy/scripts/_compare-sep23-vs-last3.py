#!/usr/bin/env python3
"""Compare Sep 23-25 vs last 3 days: Binance REALIZED_PNL + scanner exit reasons. READ-ONLY."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
python3 - <<'PY'
import json, time, hmac, hashlib, urllib.parse, urllib.request, re, gzip
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta

env={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
    if '=' in l and not l.startswith('#'):
        k,v=l.split('=',1); env[k]=v.strip().strip('"').strip("'")
key=env.get('BINANCE_API_KEY','')
secret=env.get('BINANCE_API_SECRET','')
testnet=env.get('BINANCE_TESTNET','1') in ('1','true','True','yes','on')
base='https://testnet.binancefuture.com' if testnet else 'https://fapi.binance.com'
print('MODE', 'testnet' if testnet else 'mainnet', 'base', base)

def signed_get(path, params):
    params=dict(params)
    params['timestamp']=int(time.time()*1000)
    params['recvWindow']=60000
    q=urllib.parse.urlencode(params)
    sig=hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()
    url=f"{base}{path}?{q}&signature={sig}"
    req=urllib.request.Request(url, headers={'X-MBX-APIKEY': key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

now=datetime.now(timezone.utc)
# Windows (UTC calendar days)
BASE_DAYS={'2026-09-23','2026-09-24','2026-09-25'}
# past 3 full UTC days ending yesterday + today so far
last3=set()
for i in range(0,3):
    last3.add((now - timedelta(days=i)).strftime('%Y-%m-%d'))
print('BASE_DAYS', sorted(BASE_DAYS))
print('LAST3_DAYS', sorted(last3))

start=int(datetime(2026,9,23,tzinfo=timezone.utc).timestamp()*1000)
end=int(now.timestamp()*1000)+1000
rows=[]
cursor=start
while cursor < end:
    chunk_end=min(cursor + 5*24*3600*1000, end)
    try:
        part=signed_get('/fapi/v1/income', {
            'incomeType':'REALIZED_PNL','startTime':cursor,'endTime':chunk_end,'limit':1000
        })
    except Exception as e:
        print('INCOME_ERR', e); break
    if not part:
        cursor=chunk_end+1; continue
    rows.extend(part)
    last=max(int(x.get('time') or 0) for x in part)
    if last <= cursor:
        cursor=chunk_end+1
    else:
        cursor=last+1
    if len(part) < 1000:
        cursor=chunk_end+1

print('INCOME_ROWS', len(rows))

by_day=defaultdict(float)
by_day_n=defaultdict(int)
by_day_sym=defaultdict(lambda: defaultdict(float))
by_win=defaultdict(float)
by_win_n=defaultdict(int)
by_win_sym=defaultdict(lambda: defaultdict(float))
fills=[]

for r in rows:
    try:
        pnl=float(r.get('income') or 0)
    except Exception:
        continue
    t=int(r.get('time') or 0)
    day=datetime.fromtimestamp(t/1000, timezone.utc).strftime('%Y-%m-%d')
    sym=str(r.get('symbol') or '')
    by_day[day]+=pnl
    by_day_n[day]+=1
    by_day_sym[day][sym]+=pnl
    win=None
    if day in BASE_DAYS: win='SEP23_25'
    elif day in last3: win='LAST3'
    if win:
        by_win[win]+=pnl
        by_win_n[win]+=1
        by_win_sym[win][sym]+=pnl
        fills.append((win, day, sym, pnl, t))

print('\n=== DAILY REALIZED PnL (all since Sep23) ===')
for day in sorted(by_day):
    tag=''
    if day in BASE_DAYS: tag=' [BASE]'
    elif day in last3: tag=' [LAST3]'
    print(f'{day}{tag} n={by_day_n[day]} pnl={round(by_day[day],2)}')

print('\n=== WINDOW TOTALS ===')
for w in ('SEP23_25','LAST3'):
    print(w, 'fills', by_win_n[w], 'pnl', round(by_win[w],2),
          'avg', round(by_win[w]/by_win_n[w],4) if by_win_n[w] else 0)
    wins=[x for x in fills if x[0]==w and x[3]>0]
    losses=[x for x in fills if x[0]==w and x[3]<0]
    print('  win_fills', len(wins), 'loss_fills', len(losses),
          'sum_wins', round(sum(x[3] for x in wins),2),
          'sum_losses', round(sum(x[3] for x in losses),2))
    print('  worst5:')
    for win,day,sym,pnl,t in sorted([x for x in fills if x[0]==w], key=lambda x:x[3])[:5]:
        print('   ', day, sym, round(pnl,2))
    print('  best5:')
    for win,day,sym,pnl,t in sorted([x for x in fills if x[0]==w], key=lambda x:x[3], reverse=True)[:5]:
        print('   ', day, sym, round(pnl,2))
    print('  by_symbol worst8:')
    for s,v in sorted(by_win_sym[w].items(), key=lambda kv: kv[1])[:8]:
        print('   ', s, round(v,2))

# Commission separately
comm_rows=[]
cursor=start
while cursor < end:
    chunk_end=min(cursor + 5*24*3600*1000, end)
    try:
        part=signed_get('/fapi/v1/income', {
            'incomeType':'COMMISSION','startTime':cursor,'endTime':chunk_end,'limit':1000
        })
    except Exception as e:
        print('COMM_ERR', e); break
    if not part:
        cursor=chunk_end+1; continue
    comm_rows.extend(part)
    last=max(int(x.get('time') or 0) for x in part)
    if last <= cursor:
        cursor=chunk_end+1
    else:
        cursor=last+1
    if len(part) < 1000:
        cursor=chunk_end+1

comm_win=defaultdict(float)
for r in comm_rows:
    try:
        pnl=float(r.get('income') or 0)
    except Exception:
        continue
    day=datetime.fromtimestamp(int(r.get('time') or 0)/1000, timezone.utc).strftime('%Y-%m-%d')
    if day in BASE_DAYS: comm_win['SEP23_25']+=pnl
    elif day in last3: comm_win['LAST3']+=pnl
print('\n=== COMMISSION ===')
for w in ('SEP23_25','LAST3'):
    print(w, 'commission', round(comm_win[w],2), 'net_approx', round(by_win[w]+comm_win[w],2))

# Scanner exit reasons from logs
print('\n=== SCANNER EXIT REASONS FROM LOGS ===')
LOG_DIR=Path('/var/log/bilshenz')
parts=[]
for name in sorted(LOG_DIR.glob('binance-api.log*')):
    try:
        if str(name).endswith('.gz'):
            with gzip.open(name,'rt',errors='replace') as f:
                parts.append(f.read())
        else:
            parts.append(name.read_text(errors='replace'))
    except Exception as e:
        print('LOG_FAIL', name, e)
text='\n'.join(parts)
print('LOG_CHARS', len(text))

# pair close reasons
re_close=re.compile(
    r'^(20\d{2}-\d{2}-\d{2})T[^\n]*scanner closed ([A-Z0-9]+) reason=([A-Z0-9_]+)',
    re.M
)
re_leg=re.compile(
    r'^(20\d{2}-\d{2}-\d{2})T[^\n]*closed leg ([A-Z0-9]+) (long1|long2|short) reason=([A-Z0-9_]+)',
    re.M
)
re_inval=re.compile(
    r'^(20\d{2}-\d{2}-\d{2})T[^\n]*INVALIDATION adverse=([0-9.]+)',
    re.M
)
re_solo=re.compile(
    r'^(20\d{2}-\d{2}-\d{2})T[^\n]*(LONG1_PULLBACK|LONG2_PULLBACK|LONG1_TP|LONG2_TP)',
    re.M
)
re_4131=re.compile(
    r'^(20\d{2}-\d{2}-\d{2})T[^\n]*(-4131|PERCENT_PRICE|force_flat_4131|PARTIAL_CLOSE|stuck_close)',
    re.M
)
re_manual=re.compile(
    r'^(20\d{2}-\d{2}-\d{2})T[^\n]*(manual|MANUAL|CLOSE_OK).*',
    re.M
)
re_lev=re.compile(
    r'^(20\d{2}-\d{2}-\d{2})T[^\n]*(ensure_exchange_leverage|naked|10x|SHORT_LEVERAGE)',
    re.M
)

def bucket(day):
    if day in BASE_DAYS: return 'SEP23_25'
    if day in last3: return 'LAST3'
    return None

for label, pattern in (
    ('PAIR_CLOSE', re_close),
    ('LEG_CLOSE', re_leg),
):
    ctr=defaultdict(Counter)
    for m in pattern.finditer(text):
        day=m.group(1)
        w=bucket(day)
        if not w: continue
        if label=='PAIR_CLOSE':
            reason=m.group(3)
        else:
            reason=f'{m.group(3)}:{m.group(4)}'
        ctr[w][reason]+=1
    print(label)
    for w in ('SEP23_25','LAST3'):
        print(' ', w, dict(ctr[w].most_common(20)), 'TOTAL', sum(ctr[w].values()))

inval=defaultdict(list)
for m in re_inval.finditer(text):
    w=bucket(m.group(1))
    if w: inval[w].append(float(m.group(2)))
print('INVALIDATION_HITS')
for w in ('SEP23_25','LAST3'):
    xs=inval[w]
    print(' ', w, 'n', len(xs), 'avg_adverse', round(sum(xs)/len(xs),2) if xs else 0, 'max', max(xs) if xs else 0)

solo=defaultdict(Counter)
for m in re_solo.finditer(text):
    w=bucket(m.group(1))
    if w: solo[w][m.group(2)]+=1
print('SOLO_HEDGE_EXIT_MARKERS')
for w in ('SEP23_25','LAST3'):
    print(' ', w, dict(solo[w]))

err4131=defaultdict(int)
for m in re_4131.finditer(text):
    w=bucket(m.group(1))
    if w: err4131[w]+=1
print('STUCK_EXIT_4131_MARKERS', dict(err4131))

# Oversize / AAVE / manual bombs
re_manual_qty=re.compile(
    r'^(20\d{2}-\d{2}-\d{2})T[^\n]*manual=True.*qty=([0-9.]+)',
    re.M
)
re_exec_manual=re.compile(
    r'^(20\d{2}-\d{2}-\d{2})T[^\n]*EXEC_OK coin=([A-Z0-9]+) side=(\w+) qty=([0-9.]+) fill=([0-9.]+).*manual=True',
    re.M
)
print('\n=== MANUAL OPENS ===')
for w in ('SEP23_25','LAST3'):
    man=[]
    for m in re_exec_manual.finditer(text):
        if bucket(m.group(1))!=w: continue
        qty=float(m.group(4)); fill=float(m.group(5))
        notional=qty*fill
        man.append((m.group(1), m.group(2), m.group(3), qty, fill, notional))
    print(w, 'n', len(man))
    for row in sorted(man, key=lambda x: -x[5])[:8]:
        print(' ', row[0], row[1], row[2], 'qty', row[3], 'px', row[4], 'notional', round(row[5],2))

# Leverage on closes / adopts
re_lev_open=re.compile(
    r'^(20\d{2}-\d{2}-\d{2})T[^\n]*exchange leverage ([A-Z0-9]+) .*?(\d+)x',
    re.M
)
print('\n=== LIVE ACCOUNT ===')
try:
    acct=signed_get('/fapi/v2/account', {})
    print('wallet', round(float(acct.get('totalWalletBalance') or 0),2),
          'upnl', round(float(acct.get('totalUnrealizedProfit') or 0),2),
          'avail', round(float(acct.get('availableBalance') or 0),2))
except Exception as e:
    print('acct_err', e)

# Current knobs
import sys
sys.path.insert(0,'/opt/bilshenz/binance_trading_system/python')
import momentum_scanner as ms
from frozen_strategy import assert_frozen_contract
snap=assert_frozen_contract()
print('\n=== LIVE KNOBS ===')
print('part', ms.LOCKED_PARTITION_USD, 'smart', ms.SMART_EXIT_NET_PCT,
      'inv', ms.PAIR_INVALIDATION_PCT, 'l1', ms.LONG1_ADVERSE_PCT, 'l2', ms.LONG2_ADVERSE_PCT,
      'short_tp', ms.SHORT_TP_PCT, 'long_pb', ms.LONG_HEDGE_PULLBACK_PCT)
print('ops', snap.get('ops'))
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=240)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-3000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
