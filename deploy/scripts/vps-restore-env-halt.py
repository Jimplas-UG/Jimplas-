#!/usr/bin/env python3
"""Fully restore /etc/bilshenz.env from smashed single-line / literal \\n content."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"

CMD = r'''
set -e
python3 <<'PY'
from pathlib import Path
import re

candidates = []
for p in [
    Path('/etc/bilshenz.env.smashed.bak'),
    Path('/etc/bilshenz.env'),
]:
    if p.exists():
        candidates.append(p)

# also search recent backups
for p in Path('/etc').glob('bilshenz.env*'):
    candidates.append(p)
for p in Path('/root').glob('**/bilshenz.env*'):
    candidates.append(p)

best=None
best_score=-1
for p in candidates:
    raw=p.read_text(encoding='utf-8', errors='replace')
    # expand literal backslash-n
    text=raw.replace('\\n','\n')
    lines=[ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith('#') and '=' in ln]
    keys=set()
    for ln in lines:
        k=ln.split('=',1)[0].strip()
        keys.add(k)
    score=len(keys)
    # prefer files with critical keys
    for need in ('BRIDGE_TOKEN','SESSION_ENC_KEY','DESK_API_KEY','BINANCE_FORCE_MAINNET'):
        if need in keys:
            score += 5
    print(f'cand {p} score={score} keys={sorted(keys)[:20]} n={len(keys)}')
    if score > best_score:
        best_score=score
        best=(p, text, keys)

if not best or best_score < 5:
    raise SystemExit('NO_GOOD_BACKUP')

src, text, keys = best
# rebuild clean env from text lines
kv={}
order=[]
for ln in text.splitlines():
    if not ln.strip() or ln.strip().startswith('#'):
        continue
    if '=' not in ln:
        continue
    k,v=ln.split('=',1)
    k=k.strip()
    if not k or k in kv:
        # keep first occurrence of each key
        if k in kv:
            continue
    kv[k]=v
    order.append(k)

# force halt
kv['SCANNER_EXEC']='0'
kv['FORWARD_DRY_RUN']='1'
if 'SCANNER_EXEC' not in order: order.append('SCANNER_EXEC')
if 'FORWARD_DRY_RUN' not in order: order.append('FORWARD_DRY_RUN')

out=[]
seen=set()
for k in order:
    if k in seen: continue
    seen.add(k)
    out.append(f'{k}={kv[k]}')

Path('/etc/bilshenz.env.pre-repair').write_text(Path('/etc/bilshenz.env').read_text(encoding='utf-8', errors='replace'), encoding='utf-8')
Path('/etc/bilshenz.env').write_text('\n'.join(out)+'\n', encoding='utf-8')
print('RESTORED_FROM', src)
print('FINAL_LINES', len(out))
for k in sorted(kv):
    v=kv[k].strip().strip('"').strip("'")
    if 'KEY' in k or 'SECRET' in k or 'TOKEN' in k:
        print(f'{k} len={len(v)}')
    else:
        print(f'{k}={v}')
PY

# restart with repaired env
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 6
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
''' + PY + r''' - <<'PY'
import os, json, urllib.request, time
for line in open('/etc/bilshenz.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1)
    os.environ[k.strip()]=v.strip().strip('"').strip("'")
from session_store import load_binance_session
s=load_binance_session()
print('session_load', bool(s), 'testnet', (s or {}).get('testnet'))
# wait for auto-restore
for i in range(15):
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
    sc=h.get('scanner') or {}
    print(i, 'connected', h.get('connected'), 'block', sc.get('exec_block'), 'can', sc.get('can_execute'),
          'user', (h.get('user_data_stream') or {}).get('ws_connected'))
    if h.get('connected') and sc.get('exec_block') in ('SCANNER_EXEC=0','FORWARD_DRY_RUN'):
        print('HALTED_AND_CONNECTED')
        break
    if h.get('connected'):
        print('CONNECTED_CHECK_BLOCK')
        break
    time.sleep(1)
PY
journalctl -u bilshenz-binance-api --since '20 seconds ago' --no-pager | grep -iE 'session|persisted|restore|mismatch|FORCE_MAINNET|HALT|SCANNER' | tail -25
'''

pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
_, o, e = c.exec_command(CMD, timeout=120)
print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
err=e.read().decode("utf-8", "replace")
if err.strip():
    print('STDERR', err.encode("ascii", "replace").decode("ascii")[-2500:])
c.close()
