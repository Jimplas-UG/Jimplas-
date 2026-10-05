#!/usr/bin/env python3
from pathlib import Path
import paramiko, gzip
HOST='159.223.29.223'
KEY=Path.home()/'.ssh'/'id_ed25519'
CMD=r'''
python3 - <<'PY'
import gzip, re
from collections import Counter
from pathlib import Path

def read_gz(p):
    return gzip.open(p,'rt',errors='replace').read() if str(p).endswith('.gz') else Path(p).read_text(errors='replace')

for day, path in [
 ('2026-09-23','/var/log/bilshenz/binance-api.log.8.gz'),
 ('2026-09-24','/var/log/bilshenz/binance-api.log.7.gz'),
 ('2026-09-25','/var/log/bilshenz/binance-api.log.6.gz'),
]:
    p=Path(path)
    # find file containing day
    cands=list(Path('/var/log/bilshenz').glob('binance-api.log*'))
    text=''
    for cand in sorted(cands):
        try:
            t=read_gz(cand)
        except Exception:
            continue
        if day in t:
            text=t
            used=cand.name
            break
    if not text:
        print(day, 'NO_LOG')
        continue
    lines=[ln for ln in text.splitlines() if day in ln]
    c=Counter()
    smart=[]
    for ln in lines:
        if 'SMART_EXIT' in ln and 'pnl=' in ln:
            c['smart_decide']+=1
            m=re.search(r'pnl=([-0-9.]+) target=([-0-9.]+)', ln)
            if m: smart.append((float(m.group(1)), float(m.group(2)), ln[11:19]))
        if 'reason=SMART_EXIT' in ln: c['smart_close']+=1
        if 'manual close leg' in ln: c['manual_leg']+=1
        if 'MANUAL_SHORT_FLATTEN' in ln: c['manual_flat']+=1
        if 'MANUAL_PAIR' in ln: c['manual_pair']+=1
        if 'scanner SHORT ' in ln and 'qty=' in ln and 'failed' not in ln: c['short_ok']+=1
        if 'scanner SHORT failed' in ln: c['short_fail']+=1
        if 'EXEC_FAIL' in ln and 'cooling' in ln: c['cool_fail']+=1
        if 'reason=SHORT_TP' in ln: c['short_tp']+=1
        if 'reason=RESCUE' in ln: c['rescue']+=1
        if 'waiting' in ln and 'REST cool' in ln: c['cool_wait']+=1
        if 'clearing' in ln and 'cool' in ln: c['cool_clear']+=1
    print(day, 'file', used if text else None, 'lines', len(lines), dict(c))
    for s in smart[:6]:
        print('  smart', s)
PY
'''
pkey=paramiko.Ed25519Key.from_private_key_file(str(KEY))
c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username='root', pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
_,o,e=c.exec_command(CMD, timeout=180)
print(o.read().decode())
print(e.read().decode()[-500:])
c.close()
