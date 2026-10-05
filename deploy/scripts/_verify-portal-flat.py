#!/usr/bin/env python3
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=40, look_for_keys=False, allow_agent=False)
CMD = r'''
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
import json, urllib.request
from pathlib import Path
tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health',timeout=8).read())
sc=h.get('scanner') or {}
req=urllib.request.Request('http://127.0.0.1:8766/api/positions',headers={'Authorization':'Bearer '+tok})
pos=json.loads(urllib.request.urlopen(req,timeout=12).read())
print('can', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'), 'block', sc.get('exec_block'), 'active', sc.get('active_symbol'))
items=pos.get('positions') or []
print('positions', len(items))
for p in items:
    print(' ', p.get('symbol'), p.get('positionSide'), p.get('volume'), p.get('profit'))
text=Path('/var/log/bilshenz/binance-api.log').read_text(errors='replace')
hits=[ln for ln in text.splitlines() if 'PORTAL' in ln and ('chunk' in ln.lower() or 'closed' in ln or 'FLAT' in ln or 'orphan' in ln or '4005' in ln)]
for ln in hits[-15:]:
    print(ln[:220])
PY
'''
_, o, e = c.exec_command(CMD, timeout=60)
print(o.read().decode('utf-8','replace').encode('ascii','replace').decode('ascii'))
c.close()
