#!/usr/bin/env python3
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
ls -lah /opt/bilshenz/frontend/dist/bilshenz*.apk
sha256sum /opt/bilshenz/frontend/dist/bilshenz-release.apk
cp -f /opt/bilshenz/frontend/dist/bilshenz.apk /var/www/html/bilshenz.apk 2>/dev/null || true
mkdir -p /var/www/html
cp -f /opt/bilshenz/frontend/dist/bilshenz.apk /var/www/html/bilshenz.apk
cp -f /opt/bilshenz/frontend/dist/bilshenz-release.apk /var/www/html/bilshenz-release.apk
ls -lah /var/www/html/bilshenz*.apk
for u in http://127.0.0.1/bilshenz.apk http://127.0.0.1:8791/apk http://127.0.0.1:8766/health; do
  echo "== $u =="
  curl -sS -I --max-time 6 "$u" 2>/dev/null | head -n 4 || true
done
systemctl is-active bilshenz-binance-api
python3 - <<'PY'
import json,urllib.request
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health',timeout=8).read())
sc=h.get('scanner') or {}
print('health conn', h.get('connected'), 'can', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'))
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=40)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err.encode("ascii", "replace").decode("ascii")[-500:])
    c.close()

if __name__ == "__main__":
    main()
