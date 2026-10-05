#!/usr/bin/env python3
"""Forensic: Long1 misses / margin blocks after balance drawdown (read-only)."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=30, look_for_keys=False, allow_agent=False)

CMD = r"""
python3 <<'PY'
import json, re, subprocess
from collections import defaultdict

# Health snapshot
try:
    import urllib.request
    h=json.load(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=6))
    sc=h.get('scanner') or {}
    print('HALT can_execute', sc.get('can_execute'), 'block', sc.get('exec_block'), 'halted', sc.get('user_exec_halted'))
    print('partition', sc.get('partition_usd'), 'active', sc.get('active_symbol'))
    print('last_exec_error', sc.get('last_exec_error'))
    print('--- recent events ---')
    for e in (sc.get('execution_events') or [])[:25]:
        print(json.dumps({k:e.get(k) for k in ('ts','symbol','leg','stage','side','quantity','fill_price','error')}, default=str)[:350])
except Exception as ex:
    print('health err', ex)

log='/var/log/bilshenz/binance-api.log'
# Also rotated
paths=[log, log+'.1']
pat=re.compile(r'(LONG1|LONG2|SHORT|insufficient_margin|EXEC_FAIL|EXEC_OK|scanner (SHORT|LONG1|LONG2)|closed leg|invalidat|SMART_EXIT|orphan|adopted)', re.I)

print('=== MARGIN / LEG FAILURES (today) ===')
for p in paths:
    try:
        with open(p,'r',errors='replace') as f:
            for line in f:
                if '2026-10-01' not in line and 'Oct 01' not in line and 'T09:' not in line and 'T10:' not in line and 'T11:' not in line and 'T12:' not in line and 'T13:' not in line:
                    # still include if has Oct 1 iso
                    if '2026-10-01' not in line:
                        continue
                if 'insufficient_margin' in line or 'LONG1 failed' in line or 'LONG2 failed' in line or 'SHORT failed' in line or 'EXEC_FAIL' in line or 'EXEC_OK' in line or 'scanner LONG1' in line or 'scanner LONG2' in line or 'scanner SHORT' in line or 'closed leg' in line or 'INVALID' in line.upper() and 'scanner' in line:
                    if any(x in line for x in ('insufficient_margin','LONG1','LONG2','SHORT','EXEC_','closed leg','invalidat','SMART_EXIT','adopted','phantom')):
                        print(line.rstrip()[:280])
    except FileNotFoundError:
        pass

print('=== COUNT BY SYMBOL margin blocks ===')
counts=defaultdict(lambda: defaultdict(int))
for p in paths:
    try:
        text=open(p,errors='replace').read()
    except Exception:
        continue
    for m in re.finditer(r'coin=(\S+)\s+side=(\S+)\s+qty=.*?reason=(insufficient_margin[^\s]*)', text):
        counts[m.group(1)][m.group(3)] += 1
    for m in re.finditer(r'(LONG1|LONG2) failed (\S+): (insufficient_margin[^\s]*)', text):
        counts[m.group(2)][m.group(1)+':' + m.group(3)] += 1
for sym, d in sorted(counts.items(), key=lambda x: -sum(x[1].values()))[:20]:
    print(sym, dict(d))
PY
"""
_, o, e = c.exec_command(CMD, timeout=60)
out = o.read().decode("utf-8", "replace")
Path(__file__).with_name("_below90-out.txt").write_text(out, encoding="utf-8")
print(out.encode("ascii", "replace").decode("ascii")[:12000])
c.close()
