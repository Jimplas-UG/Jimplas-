#!/usr/bin/env python3
"""Recover BRIDGE_TOKEN from desk-api / backups / process; keep halt."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r'''
set +e
echo '=== search token sources (lengths only) ==='
python3 <<'PY'
from pathlib import Path
import re, os
paths=[]
for root in ['/etc','/opt/bilshenz','/root','/var/lib/bilshenz']:
  r=Path(root)
  if not r.exists():
    continue
  for p in r.rglob('*'):
    try:
      if p.is_file() and p.stat().st_size < 200_000:
        name=p.name.lower()
        if any(x in name for x in ('env','token','secret','bilshenz','bridge','desk')):
          paths.append(p)
    except Exception:
      pass
found=[]
for p in paths:
  try:
    t=p.read_text(encoding='utf-8', errors='ignore')
  except Exception:
    continue
  for m in re.finditer(r'BRIDGE_TOKEN\s*=\s*([^\n\r]*)', t):
    v=m.group(1).strip().strip('"').strip("'")
    # skip literal backslash fragments
    if '\\n' in v:
      v=v.split('\\n')[0].strip()
    if len(v) >= 16:
      found.append((str(p), len(v), v))
print('matches', len(found))
# unique by value
uniq={}
for path,ln,v in found:
  uniq.setdefault(v, path)
for v,path in uniq.items():
  print(f'len={len(v)} from={path}')
# write best into env if current empty
env=Path('/etc/bilshenz.env')
lines=env.read_text().splitlines()
cur=''
for ln in lines:
  if ln.startswith('BRIDGE_TOKEN='):
    cur=ln.split('=',1)[1].strip().strip('"').strip("'")
print('current_bridge_len', len(cur))
if len(cur)<8 and uniq:
  # prefer longest
  best=max(uniq.keys(), key=len)
  out=[]
  seen=False
  for ln in lines:
    if ln.startswith('BRIDGE_TOKEN='):
      out.append('BRIDGE_TOKEN='+best); seen=True
    else:
      out.append(ln)
  if not seen:
    out.append('BRIDGE_TOKEN='+best)
  env.write_text('\n'.join(out)+'\n')
  print('UPDATED_BRIDGE_TOKEN len', len(best))
else:
  print('NO_UPDATE_OR_OK')
PY
# desk unit env
systemctl cat bilshenz-desk-api 2>/dev/null | head -40
# if still empty, generate new token and update desk if it reads same file
python3 <<'PY'
from pathlib import Path
import secrets
env=Path('/etc/bilshenz.env')
lines=env.read_text().splitlines()
cur=''
for ln in lines:
  if ln.startswith('BRIDGE_TOKEN='):
    cur=ln.split('=',1)[1].strip().strip('"').strip("'")
if len(cur)>=16:
  print('KEEP_EXISTING', len(cur))
else:
  tok=secrets.token_urlsafe(32)
  out=[]
  seen=False
  for ln in lines:
    if ln.startswith('BRIDGE_TOKEN='):
      out.append('BRIDGE_TOKEN='+tok); seen=True
    else:
      out.append(ln)
  if not seen:
    out.append('BRIDGE_TOKEN='+tok)
  env.write_text('\n'.join(out)+'\n')
  print('GENERATED_NEW_BRIDGE_TOKEN len', len(tok))
PY
systemctl restart bilshenz-binance-api bilshenz-desk-api
sleep 4
python3 <<'PY'
from pathlib import Path
raw=Path('/etc/bilshenz.env').read_text()
for ln in raw.splitlines():
  if ln.startswith('BRIDGE_TOKEN='):
    print('final_bridge_len', len(ln.split('=',1)[1].strip()))
  if ln.startswith('SCANNER_EXEC=') or ln.startswith('FORWARD_DRY_RUN='):
    print(ln)
PY
curl -sS -m 4 http://127.0.0.1:8766/health | python3 -c 'import sys,json;h=json.load(sys.stdin);sc=h.get("scanner") or {};print("connected",h.get("connected"),"block",sc.get("exec_block"),"can",sc.get("can_execute"))'
curl -sS -m 4 http://127.0.0.1:8791/health | head -c 200; echo
'''

pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
_, o, e = c.exec_command(CMD, timeout=90)
print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
print(e.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii")[-1500:])
c.close()
