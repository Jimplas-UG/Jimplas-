#!/usr/bin/env python3
"""Force mainnet + re-login with working session/env keys; verify orders path clears -2015."""
from __future__ import annotations

from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"

CMD = r'''
set -e
python3 <<'PY'
from pathlib import Path
p = Path('/etc/bilshenz.env')
raw = p.read_text(encoding='utf-8')
if raw.count('\n') < 10:
    raise SystemExit('REFUSE_SMASHED')
lines = raw.splitlines()
kv = {}
order = []
for ln in lines:
    if not ln.strip() or ln.strip().startswith('#') or '=' not in ln:
        continue
    k, v = ln.split('=', 1)
    k = k.strip()
    if k not in kv:
        order.append(k)
    kv[k] = v
# force mainnet live
kv['BINANCE_TESTNET'] = '0'
kv['BINANCE_FORCE_TESTNET'] = '0'
kv['BINANCE_FORCE_MAINNET'] = '1'
kv['BINANCE_PAPER'] = '0'
kv['SCANNER_EXEC'] = '1'
kv['FORWARD_DRY_RUN'] = '0'
for k in ('BINANCE_FORCE_MAINNET','BINANCE_FORCE_TESTNET','BINANCE_TESTNET','BINANCE_PAPER','SCANNER_EXEC','FORWARD_DRY_RUN'):
    if k not in order:
        order.append(k)
out = [f'{k}={kv[k]}' for k in order]
Path('/etc/bilshenz.env.pre-2015-fix').write_text(raw, encoding='utf-8')
p.write_text('\n'.join(out) + '\n', encoding='utf-8')
print('ENV_MAINNET_LOCKED')
for k in ('BINANCE_TESTNET','BINANCE_FORCE_MAINNET','BINANCE_FORCE_TESTNET','SCANNER_EXEC','FORWARD_DRY_RUN'):
    print(f'{k}={kv[k]}')
print('APIKEY_len', len(kv.get('BINANCE_API_KEY','').strip().strip('"').strip("'")))
print('SESSION_ENC_len', len(kv.get('SESSION_ENC_KEY','').strip().strip('"').strip("'")))
print('BRIDGE_len', len(kv.get('BRIDGE_TOKEN','').strip().strip('"').strip("'")))
PY

systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 7
systemctl is-active bilshenz-binance-api bilshenz-forward-bot

cd /opt/bilshenz/binance_trading_system/python
''' + PY + r''' <<'PY'
import os, json, time, urllib.request

for line in open('/etc/bilshenz.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1)
    os.environ[k.strip()] = v.strip().strip('"').strip("'")

from session_store import load_binance_session, save_binance_session

s = load_binance_session()
env_key = os.environ.get('BINANCE_API_KEY','').strip()
env_sec = os.environ.get('BINANCE_API_SECRET','').strip()

# Prefer whichever keys we already proved work on mainnet.
# If both exist and differ, prefer session (phone Connect), else env.
if s and s.get('api_key') and s.get('api_secret'):
    key, sec = s['api_key'], s['api_secret']
    src = 'session'
else:
    key, sec = env_key, env_sec
    src = 'env'
print('login_src', src, 'key_len', len(key))

# Persist as mainnet session so restore stays correct
save_binance_session(key, sec, False)
print('session_saved_mainnet')

tok = os.environ.get('BRIDGE_TOKEN','').strip()
body = json.dumps({'api_key': key, 'api_secret': sec, 'testnet': False}).encode()
req = urllib.request.Request(
    'http://127.0.0.1:8766/api/login',
    data=body,
    headers={'Content-Type':'application/json','Authorization': f'Bearer {tok}'},
    method='POST',
)
try:
    with urllib.request.urlopen(req, timeout=45) as r:
        j = json.loads(r.read())
    print('login', {k:j.get(k) for k in ('ok','connected','testnet','error','detail','account') if k in j or True})
    if isinstance(j.get('account'), dict):
        print('acct_keys', list(j['account'].keys())[:12])
except Exception as e:
    print('login_fail', e)
    if hasattr(e, 'read'):
        print(e.read().decode('utf-8','replace')[:400])

time.sleep(2)
h = json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
sc = h.get('scanner') or {}
print('health connected', h.get('connected'), 'testnet', h.get('testnet'),
      'can', sc.get('can_execute'), 'block', sc.get('exec_block'),
      'user', (h.get('user_data_stream') or {}).get('ws_connected'))

# Signed account via bridge status
req2 = urllib.request.Request('http://127.0.0.1:8766/api/status', headers={'Authorization': f'Bearer {tok}'})
try:
    with urllib.request.urlopen(req2, timeout=15) as r:
        st = json.loads(r.read())
    print('status_ok', st.get('ok'), 'connected', st.get('connected'), 'testnet', st.get('testnet'))
    print('status_err', st.get('error') or st.get('detail'))
except Exception as e:
    print('status_fail', e)

# positions should not -2015
req3 = urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={'Authorization': f'Bearer {tok}'})
try:
    with urllib.request.urlopen(req3, timeout=15) as r:
        pos = json.loads(r.read())
    print('positions_ok', pos.get('ok'), 'n', len(pos.get('positions') or []), 'err', pos.get('error'))
except Exception as e:
    print('positions_fail', e)
    if hasattr(e,'read'):
        print(e.read().decode('utf-8','replace')[:300])

# recent log after fix
import subprocess
out = subprocess.check_output(['bash','-lc',"grep -iE '2015|Invalid API-key|EXEC_FAIL|session restored|login' /var/log/bilshenz/binance-api.log | tail -15"], text=True)
print(out)
PY
'''

def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=120)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print(err.encode("ascii", "replace").decode("ascii")[-2500:])
    c.close()

if __name__ == "__main__":
    main()
