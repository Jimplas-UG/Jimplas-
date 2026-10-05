#!/usr/bin/env python3
"""Pull income + close-reason detail for Oct1 and mainnet flip window. READ-ONLY."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
python3 - <<'PY'
import json, time, hmac, hashlib, urllib.parse, urllib.request
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

env={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
    if '=' in l and not l.startswith('#'):
        k,v=l.split('=',1); env[k]=v.strip().strip('"').strip("'")
# prefer live session if available
sess={}
sp=Path('/var/lib/bilshenz/binance-session.json')
if sp.exists():
    try: sess=json.loads(sp.read_text() or '{}')
    except: pass
# session may be encrypted blob v/p/s — use env keys
key=env.get('BINANCE_API_KEY','')
secret=env.get('BINANCE_API_SECRET','')
testnet=env.get('BINANCE_TESTNET','1') in ('1','true','True')
base='https://testnet.binancefuture.com' if testnet else 'https://fapi.binance.com'
print('using', base, 'key_len', len(key))

def signed_get(path, params):
    params=dict(params)
    params['timestamp']=int(time.time()*1000)
    params['recvWindow']=60000
    q=urllib.parse.urlencode(params)
    sig=hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()
    url=f"{base}{path}?{q}&signature={sig}"
    req=urllib.request.Request(url, headers={'X-MBX-APIKEY': key})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

# Realized PnL income last 10 days
start=int(datetime(2026,9,23,tzinfo=timezone.utc).timestamp()*1000)
end=int(datetime(2026,10,2,tzinfo=timezone.utc).timestamp()*1000)
rows=[]
cursor=start
while cursor < end:
    chunk_end=min(cursor + 6*24*3600*1000, end)
    try:
        part=signed_get('/fapi/v1/income', {'incomeType':'REALIZED_PNL','startTime':cursor,'endTime':chunk_end,'limit':1000})
    except Exception as e:
        print('income_err', e); break
    if not part:
        cursor=chunk_end+1; continue
    rows.extend(part)
    # paginate by last time
    last=max(int(x.get('time') or 0) for x in part)
    if last <= cursor:
        cursor=chunk_end+1
    else:
        cursor=last+1
    if len(part) < 1000:
        cursor=chunk_end+1

print('income_rows', len(rows))
by_day=defaultdict(float)
by_day_n=defaultdict(int)
by_sym=defaultdict(float)
worst=[]
for r in rows:
    try:
        pnl=float(r.get('income') or 0)
    except: continue
    t=int(r.get('time') or 0)
    day=datetime.fromtimestamp(t/1000, timezone.utc).strftime('%Y-%m-%d')
    by_day[day]+=pnl
    by_day_n[day]+=1
    by_sym[r.get('symbol')]+=pnl
    worst.append((pnl, day, r.get('symbol'), t))
for day in sorted(by_day):
    print(day, 'n', by_day_n[day], 'pnl', round(by_day[day],2))
print('TOTAL', round(sum(by_day.values()),2))
print('WORST15')
for pnl,day,sym,t in sorted(worst)[:15]:
    print(datetime.fromtimestamp(t/1000,timezone.utc).isoformat(), sym, round(pnl,2))
print('BEST10')
for pnl,day,sym,t in sorted(worst, reverse=True)[:10]:
    print(datetime.fromtimestamp(t/1000,timezone.utc).isoformat(), sym, round(pnl,2))
print('BY_SYM worst10')
for s,v in sorted(by_sym.items(), key=lambda kv: kv[1])[:10]:
    print(s, round(v,2))

# account
try:
    acct=signed_get('/fapi/v2/account', {})
    print('balance', acct.get('totalWalletBalance'), 'upnl', acct.get('totalUnrealizedProfit'), 'avail', acct.get('availableBalance'))
except Exception as e:
    print('acct_err', e)
PY
"""

def main():
    pkey=paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username='root', pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _,o,e=c.exec_command(CMD, timeout=120)
    print(o.read().decode('utf-8','replace'))
    err=e.read().decode('utf-8','replace')
    if err.strip(): print('STDERR', err[-800:])
    c.close()
if __name__=='__main__':
    main()
