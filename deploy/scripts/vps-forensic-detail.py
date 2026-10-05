#!/usr/bin/env python3
"""Detail pass: partition timeline, MOVR cycle, fees, Oct1 gap. READ-ONLY."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
python3 <<'PY'
import gzip, json, re, time, hmac, hashlib, urllib.parse, urllib.request
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

LOG_DIR=Path('/var/log/bilshenz')

def open_log(p):
    return gzip.open(p,'rt',errors='replace') if str(p).endswith('.gz') else p.open('rt',errors='replace')

print('=== PARTITION / RISK / NOTIONAL TIMELINE ===')
# from shorts qty*px and risk file logs
pat_part=re.compile(r'partition[_ =]+([0-9.]+)', re.I)
pat_short=re.compile(r'(\d{4}-\d{2}-\d{2}T[\d:]+).*scanner SHORT (\w+) qty=([0-9.]+) @ ([0-9.]+)')
pat_risk=re.compile(r'(\d{4}-\d{2}-\d{2}T[\d:]+).*(partition_usd|set_risk|risk update|apply_risk|SCANNER_PARTITION)')
for path in sorted(LOG_DIR.glob('binance-api.log*'), key=lambda p:p.stat().st_mtime):
    with open_log(path) as f:
        for ln in f:
            if not (ln.startswith('2026-09-2') or ln.startswith('2026-09-3') or ln.startswith('2026-10-01')):
                continue
            if 'scanner SHORT ' in ln and 'qty=' in ln and 'failed' not in ln:
                m=pat_short.search(ln)
                if m:
                    notional=float(m.group(3))*float(m.group(4))
                    # infer partition: short is 50% * 5x = 2.5x partition => partition ~= notional/2.5
                    part=notional/2.5
                    print(m.group(1), 'SHORT', m.group(2), 'notional', round(notional,1), 'implied_partition', round(part,1))
            if 'partition_usd' in ln and any(x in ln for x in ('INFO','risk','set','update','apply')):
                if 'scanner SHORT' not in ln:
                    print('RISKLINE', ln[:220])

print('\n=== MOVR / GTC / APR FULL CYCLE LINES ===')
needles=('MOVRUSDT','GTCUSDT','APRUSDT')
for path in sorted(LOG_DIR.glob('binance-api.log*'), key=lambda p:p.stat().st_mtime):
    with open_log(path) as f:
        for ln in f:
            if not (ln.startswith('2026-09-29') or ln.startswith('2026-09-30') or ln.startswith('2026-10-01')):
                continue
            if not any(n in ln for n in needles):
                continue
            if any(x in ln for x in ('scanner SHORT ','scanner LONG','scanner closed','SMART_EXIT','RESCUE','PULLBACK','INVALIDATION','MANUAL','EXEC_OK','EXEC_FAIL','entry cooldown','adverse','opened')):
                if 'positions: Binance' in ln: continue
                print(ln[:260])

print('\n=== MANUAL FLATTENS Sep23-25 vs 29-01 ===')
for label, days in [('BASE',('2026-09-23','2026-09-24','2026-09-25')), ('RECENT',('2026-09-29','2026-09-30','2026-10-01'))]:
    print('---', label)
    for path in sorted(LOG_DIR.glob('binance-api.log*'), key=lambda p:p.stat().st_mtime):
        with open_log(path) as f:
            for ln in f:
                if not ln.startswith(days): continue
                if 'MANUAL' in ln or 'manual close' in ln.lower():
                    print(ln[:240])

print('\n=== INCOME fees + funding + realized by day ===')
env={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
    if '=' in l and not l.startswith('#'):
        k,v=l.split('=',1); env[k]=v.strip().strip('"').strip("'")
key,secret=env['BINANCE_API_KEY'], env['BINANCE_API_SECRET']
base='https://testnet.binancefuture.com'

def signed_get(path, params):
    params=dict(params); params['timestamp']=int(time.time()*1000); params['recvWindow']=60000
    q=urllib.parse.urlencode(params)
    sig=hmac.new(secret.encode(), q.encode(), hashlib.sha256).hexdigest()
    url=f"{base}{path}?{q}&signature={sig}"
    req=urllib.request.Request(url, headers={'X-MBX-APIKEY':key})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read().decode())

start=int(datetime(2026,9,23,tzinfo=timezone.utc).timestamp()*1000)
end=int(datetime(2026,10,2,tzinfo=timezone.utc).timestamp()*1000)
all_rows=[]
for itype in ('REALIZED_PNL','COMMISSION','FUNDING_FEE'):
    cursor=start
    while cursor<end:
        chunk_end=min(cursor+7*24*3600*1000, end)
        try:
            part=signed_get('/fapi/v1/income', {'incomeType':itype,'startTime':cursor,'endTime':chunk_end,'limit':1000})
        except Exception as e:
            print('err', itype, e); break
        all_rows.extend([(itype,x) for x in (part or [])])
        if not part:
            cursor=chunk_end+1; continue
        last=max(int(x.get('time') or 0) for x in part)
        cursor = chunk_end+1 if len(part)<1000 else last+1

by=defaultdict(lambda: defaultdict(float))
for itype,r in all_rows:
    day=datetime.fromtimestamp(int(r['time'])/1000, timezone.utc).strftime('%Y-%m-%d')
    by[day][itype]+=float(r.get('income') or 0)
    by[day]['ALL']+=float(r.get('income') or 0)
print(f"{'day':12} {'realized':>10} {'commission':>10} {'funding':>10} {'net':>10}")
for day in sorted(by):
    d=by[day]
    print(f"{day:12} {d.get('REALIZED_PNL',0):10.2f} {d.get('COMMISSION',0):10.2f} {d.get('FUNDING_FEE',0):10.2f} {d.get('ALL',0):10.2f}")

# calendar compare
import urllib.request as u
tok=''
for l in Path('/etc/bilshenz.env').read_text().splitlines():
    if l.startswith('BRIDGE_TOKEN='): tok=l.split('=',1)[1].strip().strip('"').strip("'")
req=urllib.request.Request('http://127.0.0.1:8766/api/trade-calendar?days=14', headers={'X-Bridge-Token':tok})
cal=json.loads(urllib.request.urlopen(req, timeout=12).read().decode())
print('\nCALENDAR')
for row in cal.get('days') or []:
    print(row)
print('cal_total', cal.get('total_pnl'))

# open positions now
req=urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={'X-Bridge-Token':tok})
pos=json.loads(urllib.request.urlopen(req, timeout=12).read().decode())
rows=pos if isinstance(pos,list) else pos.get('positions') or []
print('\nOPEN_NOW', len(rows))
for r in rows:
    print(r.get('symbol'), r.get('positionSide') or r.get('type'), r.get('volume') or r.get('positionAmt'), 'pnl', r.get('profit'))
PY
"""

def main():
    pkey=paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username='root', pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _,o,e=c.exec_command(CMD, timeout=240)
    out=o.read().decode('utf-8','replace')
    Path(r'c:\Users\Amoskole\Binance BSV3.2\deploy\scripts\_forensic_detail.txt').write_text(out, encoding='utf-8')
    print(out[-12000:] if len(out)>12000 else out)
    err=e.read().decode('utf-8','replace')
    if err.strip(): print('STDERR', err[-1000:])
    c.close()
if __name__=='__main__':
    main()
