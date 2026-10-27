#!/usr/bin/env python3
"""Deploy full-book positionRisk gate — stops testnet HARD→418 reconcile loop."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
UPLOAD = [
    "binance_trading_system/python/binance_connector.py",
    "binance_trading_system/python/momentum_scanner.py",
    "binance_trading_system/python/test_permanent_leak_locks.py",
]
CMD = r"""
set -e
systemctl stop bilshenz-forward-bot 2>/dev/null || true
systemctl disable bilshenz-forward-bot 2>/dev/null || true
cd /opt/bilshenz/binance_trading_system/python
rm -rf __pycache__
.venv/bin/python test_permanent_leak_locks.py 2>&1 | tail -n 12
systemctl restart bilshenz-binance-api
sleep 14
systemctl is-active bilshenz-binance-api
systemctl is-active bilshenz-forward-bot || true
python3 - <<'PY'
import json, time, urllib.request, pathlib, re
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc=h.get('scanner') or {}
print('T0', time.strftime('%H:%M:%SZ', time.gmtime()),
      'can', sc.get('can_execute'), 'cool', h.get('rest_cool_s'),
      'block', sc.get('exec_block'), 'active', sc.get('active_symbol'))
src=open('binance_connector.py', encoding='utf-8').read()
ms=open('momentum_scanner.py', encoding='utf-8').read()
print('MARK full_book_gate', 'FULL_BOOK_MIN_INTERVAL_S' in src and '_full_book_rest_allowed' in src)
print('MARK reconcile_confirmed', 'confirmed_positions' in ms and 'max_age_s=30.0' in ms)
# watch 100s for HARD/418
time.sleep(100)
h2=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc2=h2.get('scanner') or {}
print('T100', time.strftime('%H:%M:%SZ', time.gmtime()),
      'can', sc2.get('can_execute'), 'cool', h2.get('rest_cool_s'),
      'block', sc2.get('exec_block'))
since=time.strftime('%Y-%m-%dT%H:%M', time.gmtime(time.time()-120))
hard=ban=soft=0
weights=[]
with open('/var/log/bilshenz/binance-api.log', errors='replace') as fh:
    for l in fh:
        if not (l.startswith('2026-') and l[:16]>=since[:16]): continue
        if 'HARD' in l and 'weight' in l.lower(): hard+=1
        if '418 IP ban' in l: ban+=1
        if 'used weight' in l and 'HARD' not in l: soft+=1
        m=re.search(r'used weight (\d+(?:\.\d+)?)/2400', l)
        if m: weights.append(float(m.group(1)))
print('WIN2m HARD', hard, 'SOFT_lines', soft, '418', ban,
      'wmax', max(weights) if weights else 0, 'wn', len(weights))
ok = (sc2.get('can_execute') is True and float(h2.get('rest_cool_s') or 0)<=0.25
      and hard==0 and ban==0 and (not weights or max(weights)<2100))
print('VERDICT', 'PASS' if ok else 'FAIL')
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in UPLOAD:
        sftp.put(str(ROOT / rel), f"/opt/bilshenz/{rel}")
        print("uploaded", rel)
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=300)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-2000:])
    c.close()

if __name__ == "__main__":
    main()
