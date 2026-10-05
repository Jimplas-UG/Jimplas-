#!/usr/bin/env python3
"""Follow-up: wait for testnet signed_ready / user WS after env key restore."""
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=30, look_for_keys=False, allow_agent=False)
CMD = r'''
# If bridge has env keys but no session, trigger a status/account verify path.
TOK=$(grep '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2- | tr -d '"' | tr -d "'")
# best-effort: hit endpoints that warm signed auth
curl -sS -m 8 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/status >/tmp/st.json || true
curl -sS -m 8 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/account >/tmp/ac.json || true
curl -sS -m 8 http://127.0.0.1:8766/health >/tmp/h.json || true
python3 <<'PY'
import json, time, urllib.request
for i in range(20):
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
    sc=h.get('scanner') or {}
    auth=sc.get('api_auth') or {}
    print(i, 'mode', h.get('mode'), 'connected', h.get('connected'),
          'can', sc.get('can_execute'), 'block', sc.get('exec_block'),
          'signed', auth.get('signed_ready'), 'blocked', auth.get('blocked'),
          'user_ws', (h.get('user_data_stream') or {}).get('ws_connected'))
    if h.get('mode')=='testnet' and h.get('connected') and sc.get('can_execute') and auth.get('signed_ready'):
        print('TESTNET_LIVE_READY')
        break
    time.sleep(1)
# peek status/account errors (no secrets)
for path in ('/tmp/st.json','/tmp/ac.json'):
    try:
        d=json.load(open(path))
        print(path, {k:d.get(k) for k in list(d)[:12] if 'key' not in k.lower() and 'secret' not in k.lower()})
    except Exception as e:
        print(path, e)
# recent auth log
import subprocess
print(subprocess.check_output("grep -E 'testnet|login|signed|account|listenKey|-2015|401' /var/log/bilshenz/binance-api.log | tail -n 25", shell=True, text=True)[-3000:])
PY
'''
_,o,e=c.exec_command(CMD, timeout=60)
print(o.read().decode('utf-8','replace').encode('ascii','replace').decode('ascii'))
err=e.read().decode('utf-8','replace')
if err.strip():
    print(err.encode('ascii','replace').decode('ascii')[-1500:])
c.close()
