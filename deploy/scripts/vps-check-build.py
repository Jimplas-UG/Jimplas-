#!/usr/bin/env python3
import paramiko
from pathlib import Path

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=30, look_for_keys=False, allow_agent=False)
CMD = r"""
systemctl is-active bilshenz-binance-api bilshenz-desk-api
python3 - <<'PY'
from pathlib import Path
import json, urllib.request
lines=Path('/etc/bilshenz.env').read_text().splitlines()
tl=next((l.split('=',1)[1] for l in lines if l.startswith('BRIDGE_TOKEN=')), '')
print('token_len', len(tl))
h=json.load(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8))
print('connected', h.get('connected'), 'mode', h.get('mode'), 'exec', (h.get('scanner') or {}).get('can_execute'))
PY
ps -ef | grep build-apk-fra | grep -v grep || echo no_build_proc
ls -la /var/log/bilshenz/ 2>/dev/null | head -20
tail -n 40 /var/log/bilshenz/apk-build-nohup.out 2>/dev/null || echo no_nohup
tail -n 40 /var/log/bilshenz/apk-build.log 2>/dev/null || echo no_apklog
# ensure build running
if ! ps -ef | grep -v grep | grep -q build-apk-fra; then
  chmod +x /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh
  nohup bash /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh > /var/log/bilshenz/apk-build-nohup.out 2>&1 &
  echo RESTARTED_BUILD
  sleep 4
  tail -n 25 /var/log/bilshenz/apk-build-nohup.out || true
  tail -n 25 /var/log/bilshenz/apk-build.log || true
fi
"""
_, o, e = c.exec_command(CMD, timeout=60)
print(o.read().decode("ascii", "replace"))
err = e.read().decode("ascii", "replace")
if err.strip():
    print("ERR", err[-1000:])
c.close()
