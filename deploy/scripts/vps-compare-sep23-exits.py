#!/usr/bin/env python3
"""Compare SMART_EXIT / cool / manual patterns Sep 23-25 vs recent."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
python3 - <<'PY'
from pathlib import Path
from collections import Counter
import re
text = Path('/var/log/bilshenz/binance-api.log').read_text(errors='replace')
# may be rotated — also check .1
for extra in ['/var/log/bilshenz/binance-api.log.1']:
    p=Path(extra)
    if p.exists():
        text = p.read_text(errors='replace') + '\n' + text

def day_stats(day):
    lines=[ln for ln in text.splitlines() if day in ln]
    c=Counter()
    smart_pnls=[]
    for ln in lines:
        if 'SMART_EXIT' in ln and 'pnl=' in ln:
            c['smart_exit_decide'] += 1
            m=re.search(r'pnl=([-0-9.]+) target=([-0-9.]+)', ln)
            if m: smart_pnls.append((float(m.group(1)), float(m.group(2))))
        if 'reason=SMART_EXIT' in ln: c['smart_exit_close'] += 1
        if 'MANUAL_SHORT_FLATTEN' in ln: c['manual_short_flatten'] += 1
        if 'manual close leg' in ln: c['manual_leg'] += 1
        if 'MANUAL_PAIR' in ln: c['manual_pair'] += 1
        if 'scanner SHORT ' in ln and 'qty=' in ln and 'failed' not in ln: c['short_ok'] += 1
        if 'scanner SHORT failed' in ln: c['short_fail'] += 1
        if 'REST cooling' in ln and 'EXEC_FAIL' in ln: c['exec_fail_cool'] += 1
        if 'SHORT_TP' in ln and 'reason=' in ln: c['short_tp'] += 1
        if 'RESCUE' in ln and 'reason=' in ln: c['rescue'] += 1
        if 'LONG1_PULLBACK' in ln: c['l1_pb'] += 1
        if 'LONG2_PULLBACK' in ln: c['l2_pb'] += 1
        if 'clearing REST cool' in ln or 'clearing residual cool' in ln: c['cool_clear_close'] += 1
        if 'waiting' in ln and 'cool' in ln.lower() and 'close' in ln.lower(): c['cool_wait_close'] += 1
    return c, smart_pnls, len(lines)

for day in ['2026-09-23','2026-09-24','2026-09-25','2026-09-28','2026-09-29','2026-09-30']:
    c, smart, n = day_stats(day)
    print(day, 'lines', n, dict(c))
    if smart:
        print('  smart_samples', smart[:8], 'avg_pnl', sum(p for p,_ in smart)/len(smart))
PY
ls -lah /var/log/bilshenz/binance-api.log* 2>/dev/null | head
"""

def main():
    pkey=paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username='root', pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
    _,o,e=c.exec_command(CMD, timeout=120)
    print(o.read().decode('utf-8','replace'))
    err=e.read().decode('utf-8','replace')
    if err.strip(): print('STDERR', err[-500:])
    c.close()
if __name__=='__main__':
    main()
