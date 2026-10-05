#!/usr/bin/env python3
import json
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=30, look_for_keys=False, allow_agent=False)
CMD = r"""
python3 <<'PY'
from pathlib import Path
import json, os, glob
env = Path('/etc/bilshenz.env').read_text().splitlines()
for k in ['DESK_API_KEY', 'BRIDGE_TOKEN']:
    for line in env:
        if line.startswith(k + '='):
            v = line.split('=', 1)[1].strip()
            print(k + '=' + (v if v else '(empty)'))
            break
print('--- users ---')
paths = list(Path('/opt/bilshenz').rglob('*.json')) + list(Path('/var/lib').rglob('*auth*'))
for p in Path('/opt/bilshenz').rglob('*'):
    if p.is_file() and ('user' in p.name.lower() or 'auth' in str(p).lower()) and p.suffix in ('.json','.db','.sqlite'):
        print('FILE', p)
for p in [
    Path('/opt/bilshenz/backend/auth/data/users.json'),
    Path('/opt/bilshenz/backend/validation/data/users.json'),
    Path('/opt/bilshenz/backend/data/users.json'),
    Path('/var/lib/bilshenz/users.json'),
]:
    print('exists', p, p.is_file())
    if p.is_file():
        try:
            d = json.loads(p.read_text())
            print(json.dumps(d if not isinstance(d, dict) or len(str(d))<2000 else {'keys': list(d.keys())}, indent=2)[:1500])
        except Exception as e:
            print('err', e)
# list auth data dirs
os.system("find /opt/bilshenz/backend -type d -name data 2>/dev/null; ls -la /opt/bilshenz/backend/auth 2>/dev/null; ls -la /opt/bilshenz/backend/validation/data 2>/dev/null")
PY
"""
_, o, e = c.exec_command(CMD, timeout=60)
print(o.read().decode("utf-8", "replace"))
print(e.read().decode("utf-8", "replace")[-800:])
c.close()
