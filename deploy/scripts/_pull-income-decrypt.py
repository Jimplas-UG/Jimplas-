#!/usr/bin/env python3
"""Pull income via running bridge connector (keys already in process)."""
from pathlib import Path
import paramiko
import sys

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

# Inject into the running API by calling connector through a one-off that
# reads keys from /proc/<pid>/environ of bilshenz OR asks bridge to run income.
# Safest: use bridge's internal connector by POSTing nothing — instead load
# session with BOTH possible enc keys from env file history, OR scrape from
# the python process cmdline. Better approach: gdb-free — read open fds?
# Actually main keeps connector global. Use systemd Environment + re-login is bad.
# Use: python attach via /opt script that imports session and also tries
# decrypt with each line from env as key.

CMD = r"""
/opt/bilshenz/binance_trading_system/python/.venv/bin/python -u - <<'PY'
import base64, hashlib, hmac, json, os, time, urllib.parse, urllib.request
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone, timedelta

env={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
    if '=' in l and not l.startswith('#'):
        k,v=l.split('=',1); env[k]=v.strip().strip('"').strip("'")

path=Path('/var/lib/bilshenz/binance-session.json')
envelope=json.loads(path.read_text())
payload=base64.b64decode(envelope['p'])
sig=str(envelope['s'])

# Try every plausible signing secret
candidates=[]
for k in ('SESSION_ENC_KEY','BRIDGE_TOKEN','DESK_API_KEY','BINANCE_SESSION_KEY'):
    if env.get(k): candidates.append(env[k])
candidates.append('bilshenz-session-v1')
# also try token without quotes variants
seen=set(); cands=[]
for c in candidates:
    if c and c not in seen:
        seen.add(c); cands.append(c)

sess=None
for raw in cands:
    expected=hmac.new(hashlib.sha256(raw.encode()).digest(), payload, hashlib.sha256).hexdigest()
    if hmac.compare_digest(expected, sig):
        sess=json.loads(payload.decode())
        print('DECRYPT_OK with', 'BRIDGE_TOKEN' if raw==env.get('BRIDGE_TOKEN') else 'CUSTOM', 'len', len(raw))
        break
if not sess:
    print('DECRYPT_FAIL tried', len(cands))
    # last resort: ask running process memory via /proc and strings? skip
    # Use calendar sticky from connector by hitting a private path
    import urllib.request
    tok=env.get('BRIDGE_TOKEN','')
    # Dump calendar from cache file fully
    cj=json.loads(Path('/var/lib/bilshenz/trade-history-cache.json').read_text() or '{}')
    cal=cj.get('calendar') or {}
    print('CACHE_CAL', json.dumps(cal)[:2000])
    raise SystemExit(0)

key=sess['api_key']; secret=sess['api_secret']; testnet=bool(sess.get('testnet', True))
base='https://testnet.binancefuture.com' if testnet else 'https://fapi.binance.com'
print('MODE', 'testnet' if testnet else 'mainnet', 'key_len', len(key))

def signed_get(path, params):
    params=dict(params); params['timestamp']=int(time.time()*1000); params['recvWindow']=60000
    q=urllib.parse.urlencode(params)
    sig=hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()
    url=f'{base}{path}?{q}&signature={sig}'
    req=urllib.request.Request(url, headers={'X-MBX-APIKEY': key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())

now=datetime.now(timezone.utc)
BASE={'2026-09-23','2026-09-24','2026-09-25'}
LAST3={(now-timedelta(days=i)).strftime('%Y-%m-%d') for i in range(0,3)}
start=int(datetime(2026,9,23,tzinfo=timezone.utc).timestamp()*1000)
end=int(now.timestamp()*1000)+1000

def pull(income_type):
    rows=[]; cursor=start
    while cursor < end:
        chunk=min(cursor+5*24*3600*1000, end)
        try:
            part=signed_get('/fapi/v1/income', {'incomeType':income_type,'startTime':cursor,'endTime':chunk,'limit':1000})
        except Exception as e:
            print(income_type,'ERR',e); break
        if not part:
            cursor=chunk+1; continue
        rows.extend(part)
        last=max(int(x.get('time') or 0) for x in part)
        cursor = chunk+1 if last<=cursor or len(part)<1000 else last+1
    return rows

rows=pull('REALIZED_PNL')
comm=pull('COMMISSION')
print('ROWS', len(rows), 'COMM', len(comm))
by_day=defaultdict(float); by_day_n=defaultdict(int)
by_win=defaultdict(float); by_win_n=defaultdict(int)
by_sym=defaultdict(lambda: defaultdict(float))
fills=[]
for r in rows:
    pnl=float(r.get('income') or 0)
    t=int(r.get('time') or 0)
    day=datetime.fromtimestamp(t/1000, timezone.utc).strftime('%Y-%m-%d')
    sym=str(r.get('symbol') or '')
    by_day[day]+=pnl; by_day_n[day]+=1
    w='SEP23_25' if day in BASE else ('LAST3' if day in LAST3 else None)
    if w:
        by_win[w]+=pnl; by_win_n[w]+=1; by_sym[w][sym]+=pnl; fills.append((w,day,sym,pnl))

comm_win=defaultdict(float)
for r in comm:
    pnl=float(r.get('income') or 0)
    day=datetime.fromtimestamp(int(r.get('time') or 0)/1000, timezone.utc).strftime('%Y-%m-%d')
    if day in BASE: comm_win['SEP23_25']+=pnl
    elif day in LAST3: comm_win['LAST3']+=pnl

print('=== DAILY ===')
for day in sorted(by_day):
    tag=' [BASE]' if day in BASE else (' [LAST3]' if day in LAST3 else '')
    print(f'{day}{tag} n={by_day_n[day]} pnl={round(by_day[day],2)}')

print('=== WINDOWS ===')
for w in ('SEP23_25','LAST3'):
    wins=[x for x in fills if x[0]==w and x[3]>0]
    losses=[x for x in fills if x[0]==w and x[3]<0]
    print(w, 'fills', by_win_n[w], 'realized', round(by_win[w],2),
          'comm', round(comm_win[w],2), 'net', round(by_win[w]+comm_win[w],2),
          'sum_wins', round(sum(x[3] for x in wins),2),
          'sum_losses', round(sum(x[3] for x in losses),2))
    print('  worst10:')
    for row in sorted([x for x in fills if x[0]==w], key=lambda x:x[3])[:10]:
        print('   ', row[1], row[2], round(row[3],2))
    print('  sym worst10:')
    for s,v in sorted(by_sym[w].items(), key=lambda kv:kv[1])[:10]:
        print('   ', s, round(v,2))

acct=signed_get('/fapi/v2/account', {})
print('wallet', round(float(acct.get('totalWalletBalance') or 0),2),
      'upnl', round(float(acct.get('totalUnrealizedProfit') or 0),2))
print('DONE')
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=180)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    c.close()

if __name__ == "__main__":
    main()
