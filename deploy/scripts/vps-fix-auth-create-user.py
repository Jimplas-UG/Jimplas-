#!/usr/bin/env python3
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=30, look_for_keys=False, allow_agent=False)
CMD = r"""
echo '=== env auth ==='
grep -E '^(AUTH_|PRODUCTION_|DESK_)' /etc/bilshenz.env | sed -E 's/(SECRET|KEY)=.*/\1=***/'
echo '=== desk log ==='
tail -n 40 /var/log/bilshenz/desk-api.log 2>/dev/null || journalctl -u bilshenz-desk-api -n 40 --no-pager
echo '=== data dir ==='
ls -la /opt/bilshenz/backend/auth/data/ 2>/dev/null
# ensure AUTH_JWT_SECRET
python3 <<'PY'
from pathlib import Path
import secrets
p=Path('/etc/bilshenz.env')
text=p.read_text()
if 'AUTH_JWT_SECRET=' not in text or any(l.startswith('AUTH_JWT_SECRET=') and len(l.split('=',1)[1].strip())<32 for l in text.splitlines()):
    lines=[l for l in text.splitlines() if not l.startswith('AUTH_JWT_SECRET=')]
    lines.append('AUTH_JWT_SECRET=' + secrets.token_hex(32))
    if not any(l.startswith('PRODUCTION_MODE=') for l in lines):
        lines.append('PRODUCTION_MODE=1')
    p.write_text('\n'.join(lines)+'\n')
    print('AUTH_JWT_FIXED')
else:
    print('AUTH_JWT_OK')
PY
mkdir -p /opt/bilshenz/backend/auth/data
chmod 755 /opt/bilshenz/backend/auth/data
systemctl restart bilshenz-desk-api
sleep 4
systemctl is-active bilshenz-desk-api
curl -sS --max-time 15 -X POST http://127.0.0.1:8791/v1/auth/register \
  -H 'Content-Type: application/json' \
  --data-binary '{"email":"amos@bilshenz.local","password":"Bilshenz2026!","confirmPassword":"Bilshenz2026!"}'
echo
curl -sS --max-time 15 -X POST http://127.0.0.1:8791/v1/auth/login \
  -H 'Content-Type: application/json' \
  --data-binary '{"email":"amos@bilshenz.local","password":"Bilshenz2026!"}'
echo
ls -la /opt/bilshenz/backend/auth/data/
"""
_, o, e = c.exec_command(CMD, timeout=90)
print(o.read().decode("utf-8", "replace"))
err = e.read().decode("utf-8", "replace")
if err.strip():
    print("ERR", err[-1500:])
c.close()
