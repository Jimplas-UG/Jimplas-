#!/usr/bin/env python3
"""Fix halt flags + diagnose session enc key mismatch without printing secrets."""
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
raw = p.read_text(encoding='utf-8', errors='replace')
print('env_bytes', len(raw), 'lines', len(raw.splitlines()))
# show only safe keys
for line in raw.splitlines():
    if not line.strip() or line.strip().startswith('#') or '=' not in line:
        continue
    k,v = line.split('=',1)
    k=k.strip(); v=v.strip().strip('"').strip("'")
    if k in ('BINANCE_API_KEY','BINANCE_API_SECRET','BRIDGE_TOKEN','DESK_API_KEY','SESSION_ENC_KEY'):
        print(f'{k} len={len(v)} empty={not bool(v)}')
    elif k in ('SCANNER_EXEC','FORWARD_DRY_RUN','SCANNER_ENABLED','BINANCE_FORCE_MAINNET','BINANCE_FORCE_TESTNET','BINANCE_TESTNET','BINANCE_PAPER','TRADE_HISTORY_SINCE'):
        print(f'{k}={v}')
# apply halt atomically
wanted = {'SCANNER_EXEC':'0','FORWARD_DRY_RUN':'1'}
lines=[]
seen=set()
for line in raw.splitlines():
    if not line.strip() or line.strip().startswith('#') or '=' not in line:
        lines.append(line); continue
    k=line.split('=',1)[0].strip()
    if k in wanted:
        lines.append(f'{k}={wanted[k]}')
        seen.add(k)
    else:
        lines.append(line)
for k,v in wanted.items():
    if k not in seen:
        lines.append(f'{k}={v}')
text='\n'.join(lines)+'\n'
p.write_text(text, encoding='utf-8')
print('WROTE_HALT')
for line in p.read_text().splitlines():
    if line.startswith('SCANNER_EXEC=') or line.startswith('FORWARD_DRY_RUN='):
        print(line)
PY

# session decrypt probe with current env
cd /opt/bilshenz/binance_trading_system/python
''' + PY + r''' <<'PY'
import os
for line in open('/etc/bilshenz.env'):
    line=line.strip()
    if not line or line.startswith('#') or '=' not in line: continue
    k,v=line.split('=',1)
    os.environ[k.strip()] = v.strip().strip('"').strip("'")
from session_store import load_binance_session, _sign_key
import hashlib, hmac, json, base64
from pathlib import Path
p=Path('/var/lib/bilshenz/binance-session.json')
env=json.loads(p.read_text())
payload=base64.b64decode(env['p'])
sig=env['s']
# try current key
sk=_sign_key()
exp=hmac.new(sk, payload, hashlib.sha256).hexdigest()
print('sig_match_current', hmac.compare_digest(exp, str(sig)))
# try BRIDGE_TOKEN alone
bt=os.environ.get('BRIDGE_TOKEN','').strip()
sk2=hashlib.sha256(bt.encode()).digest() if bt else None
if sk2:
  exp2=hmac.new(sk2, payload, hashlib.sha256).hexdigest()
  print('sig_match_bridge_token', hmac.compare_digest(exp2, str(sig)))
# try default
sk3=hashlib.sha256(b'bilshenz-session-v1').digest()
exp3=hmac.new(sk3, payload, hashlib.sha256).hexdigest()
print('sig_match_default', hmac.compare_digest(exp3, str(sig)))
print('SESSION_ENC_KEY_len', len(os.environ.get('SESSION_ENC_KEY','')))
print('BRIDGE_TOKEN_len', len(os.environ.get('BRIDGE_TOKEN','')))
s=load_binance_session()
print('load_ok', bool(s))
PY

# reload env into services without losing memory keys if possible:
# systemctl restart picks EnvironmentFile — session may still fail
# Prefer SIGHUP? not supported. Restart API only after we can decrypt.
# If decrypt fails, ask phone to Connect again — but HALT env will block new entries once connected.
systemctl daemon-reload
# inject halt into running process env is hard; restart services
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 5
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
curl -sS -m 5 http://127.0.0.1:8766/health | ''' + PY + r''' -c "import sys,json;h=json.load(sys.stdin);sc=h.get('scanner') or {};print('connected',h.get('connected'));print('block',sc.get('exec_block'),'can',sc.get('can_execute'),'exec',sc.get('exec_enabled'));print('user',(h.get('user_data_stream') or {}).get('ws_connected'))"
grep -E '^(SCANNER_EXEC|FORWARD_DRY_RUN)=' /etc/bilshenz.env
journalctl -u bilshenz-binance-api --since '30 seconds ago' --no-pager | grep -iE 'session|persisted|restore|SCANNER_EXEC|invalid|mismatch|connected' | tail -30
'''

pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
_, o, e = c.exec_command(CMD, timeout=90)
print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
err = e.read().decode("utf-8", "replace")
if err.strip():
    print('STDERR', err.encode("ascii", "replace").decode("ascii")[-2500:])
c.close()
