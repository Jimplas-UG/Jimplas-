#!/usr/bin/env python3
"""Read-only FRA stream/sync health probe."""
from pathlib import Path
import sys
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
python3 - <<'PY'
import json, urllib.request, subprocess
from pathlib import Path
env={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
  if '=' in l and not l.startswith('#'):
    k,v=l.split('=',1); env[k]=v.strip().strip('"').strip("'")
tok=env.get('BRIDGE_TOKEN','')
def get(u, t=12):
  req=urllib.request.Request(u, headers={'X-Bridge-Token':tok})
  with urllib.request.urlopen(req, timeout=t) as r:
    return json.loads(r.read().decode())
h=get('http://127.0.0.1:8766/health')
st=get('http://127.0.0.1:8766/api/status')
s=h.get('scanner') or {}
print('mode', h.get('mode'), 'connected', h.get('connected') or st.get('connected'), 'cool', h.get('rest_cool_s'), 'testnet', st.get('testnet'))
print('partition', s.get('partition_usd'), 'exec', s.get('can_execute'), 'block', s.get('exec_block'))
print('tick', h.get('tick_stream'))
print('scanner_ws', h.get('scanner_stream'))
print('user', h.get('user_data_stream'))
print('acct_server', (st.get('account') or {}).get('server'), 'bal', (st.get('account') or {}).get('balance'))
# recent reconnect / ws errors
cmd="grep -E 'user data stream|tick stream|scanner stream|reconnect|ws_|listenKey|restarting market|Remote end closed|ConnectionClosed|open_timeout|ws_connected_but_silent|stream connected|stream error' /var/log/bilshenz/binance-api.log | tail -n 60"
print('--- LOG ---')
print(subprocess.check_output(['bash','-lc',cmd], text=True, errors='replace')[-4000:])
print('--- systemd ---')
print(subprocess.check_output(['bash','-lc','systemctl is-active bilshenz-binance-api; systemctl show bilshenz-binance-api -p ActiveEnterTimestamp --value'], text=True))
# process mem
print(subprocess.check_output(['bash','-lc',"ps -o pid,etime,%cpu,%mem,cmd -C python3 | head -n 8"], text=True, errors='replace'))
PY
"""

def main():
    pkey=paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c=paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username='root', pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _,o,e=c.exec_command(CMD, timeout=60)
    sys.stdout.buffer.write(o.read())
    err=e.read()
    if err.strip(): sys.stderr.buffer.write(err[-1000:])
    c.close()
if __name__=='__main__':
    main()
