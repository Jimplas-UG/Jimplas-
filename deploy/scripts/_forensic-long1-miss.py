#!/usr/bin/env python3
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=30, look_for_keys=False, allow_agent=False)
CMD = r"""
python3 <<'PY'
import re
from collections import defaultdict

paths=['/var/log/bilshenz/binance-api.log','/var/log/bilshenz/binance-api.log.1']
# Build timeline of SHORT open -> next LONG1 ok/fail per symbol for Oct 1
events=[]
rx=re.compile(
    r'^(?P<ts>\S+)\s+\S+\s+\[(?P<mod>[^\]]+)\]\s+(?P<msg>.*)$'
)
for p in paths:
    try:
        lines=open(p,errors='replace')
    except Exception:
        continue
    for line in lines:
        if '2026-10-01' not in line:
            continue
        m=None
        if 'scanner SHORT ' in line and 'failed' not in line and 'qty=' in line:
            mm=re.search(r'scanner SHORT (\S+) qty=', line)
            if mm: events.append(('SHORT_OK', mm.group(1), line.strip()[:220]))
        elif 'scanner LONG1 ' in line and 'failed' not in line and 'qty=' in line:
            mm=re.search(r'scanner LONG1 (\S+) qty=', line)
            if mm: events.append(('LONG1_OK', mm.group(1), line.strip()[:220]))
        elif 'LONG1 failed' in line:
            mm=re.search(r'LONG1 failed (\S+): (.+?)(?:\s+latency|$)', line)
            if mm: events.append(('LONG1_FAIL', mm.group(1), mm.group(2)[:120], line.strip()[:220]))
        elif 'LONG2 failed' in line:
            mm=re.search(r'LONG2 failed (\S+): (.+?)(?:\s+latency|$)', line)
            if mm: events.append(('LONG2_FAIL', mm.group(1), mm.group(2)[:120], line.strip()[:220]))
        elif 'insufficient_margin' in line and 'EXEC_FAIL' in line:
            mm=re.search(r'coin=(\S+)\s+side=(\S+).*reason=(insufficient_margin[^\s]*)', line)
            if mm: events.append(('MARGIN', mm.group(1), mm.group(2), mm.group(3), line.strip()[:220]))
        elif 'closed leg' in line and ('invalidat' in line.lower() or 'SMART' in line or 'reason=' in line):
            events.append(('CLOSE', line.strip()[:240]))
        elif 'PAIR_INVALID' in line or 'invalidation' in line.lower():
            events.append(('INV', line.strip()[:240]))

# Reconstruct naked shorts: SHORT_OK then no LONG1_OK before next SHORT or long stretch with LONG1_FAIL
print('=== ALL LONG1 FAILURES Oct1 ===')
for e in events:
    if e[0]=='LONG1_FAIL':
        print(e[1], e[2])
print('=== ALL MARGIN BLOCKS Oct1 ===')
for e in events:
    if e[0]=='MARGIN':
        print(e[1], e[2], e[3])
print('=== SHORT then no LONG1 before next close/short (suspect naked) ===')
# simplified per-symbol last short
last_short={}
got_l1=defaultdict(bool)
from collections import defaultdict
got_l1=defaultdict(bool)
naked=[]
for e in events:
    if e[0]=='SHORT_OK':
        sym=e[1]
        if last_short.get(sym) and not got_l1.get(sym):
            naked.append((sym, 'prev short may have missed L1', last_short[sym]))
        last_short[sym]=e[2]
        got_l1[sym]=False
    elif e[0]=='LONG1_OK':
        got_l1[e[1]]=True
    elif e[0]=='LONG1_FAIL':
        print('L1_FAIL_AT', e[1], e[2], 'after_short=', (last_short.get(e[1]) or '')[:100])

# currently open without L1 historically: list SHORT_OK with later LONG1_FAIL margin and no LONG1_OK after that short
print('=== CHRONO SHORT/L1/L2 for thin-margin window (06:00+) ===')
for e in events:
    line=e[-1] if isinstance(e[-1], str) else str(e)
    if 'T06:' in line or 'T07:' in line or 'T08:' in line or 'T09:' in line or 'T10:' in line:
        if e[0] in ('SHORT_OK','LONG1_OK','LONG1_FAIL','LONG2_FAIL','MARGIN','CLOSE','INV'):
            print(e[0], line[:200])
PY
"""
_,o,e=c.exec_command(CMD, timeout=60)
out=o.read().decode('utf-8','replace')
Path(__file__).with_name('_below90-l1.txt').write_text(out, encoding='utf-8')
print(out.encode('ascii','replace').decode('ascii')[:14000])
c.close()
