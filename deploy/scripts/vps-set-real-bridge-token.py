#!/usr/bin/env python3
"""Set BRIDGE_TOKEN from /etc/tradingbot.env (48-char live token), keep halt."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
PY = "/opt/bilshenz/binance_trading_system/python/.venv/bin/python"

CMD = r'''
set -e
python3 <<'PY'
from pathlib import Path
# prefer tradingbot.env 48-char token
tb=Path('/etc/tradingbot.env').read_text(encoding='utf-8', errors='replace')
tok=None
for ln in tb.replace('\\n','\n').splitlines():
    if ln.startswith('BRIDGE_TOKEN='):
        tok=ln.split('=',1)[1].strip().strip('"').strip("'")
        break
print('tradingbot_token_len', len(tok or ''))
if not tok or len(tok)<16:
    raise SystemExit('NO_TOKEN')
env=Path('/etc/bilshenz.env')
lines=[]
seen=False
for ln in env.read_text().splitlines():
    if ln.startswith('BRIDGE_TOKEN='):
        lines.append('BRIDGE_TOKEN='+tok); seen=True
    else:
        lines.append(ln)
if not seen:
    lines.append('BRIDGE_TOKEN='+tok)
# ensure halt
out=[]; seen_exec=seen_dry=False
for ln in lines:
    if ln.startswith('SCANNER_EXEC='):
        out.append('SCANNER_EXEC=0'); seen_exec=True
    elif ln.startswith('FORWARD_DRY_RUN='):
        out.append('FORWARD_DRY_RUN=1'); seen_dry=True
    else:
        out.append(ln)
if not seen_exec: out.append('SCANNER_EXEC=0')
if not seen_dry: out.append('FORWARD_DRY_RUN=1')
env.write_text('\n'.join(out)+'\n')
print('SET_BRIDGE_FROM_TRADINGBOT len', len(tok))
PY
systemctl restart bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot
sleep 6
systemctl is-active bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot
TOK=$(grep '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2-)
echo "bridge_len=${#TOK}"
curl -sS -m 5 http://127.0.0.1:8766/health > /tmp/h.json
curl -sS -m 8 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/diagnostics > /tmp/d.json
curl -sS -m 8 -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/positions > /tmp/p.json
''' + PY + r''' -c "
import json
h=json.load(open('/tmp/h.json')); d=json.load(open('/tmp/d.json')); p=json.load(open('/tmp/p.json'))
sc=h.get('scanner') or {}
print('connected', h.get('connected'), 'block', sc.get('exec_block'), 'can', sc.get('can_execute'))
print('diag_ok', d.get('ok'), 'user_ws', (d.get('user_data_stream') or {}).get('ws_connected'), 'scanner_ws', (d.get('scanner_stream') or {}).get('ws_connected'), 'binance_ms', d.get('binance_latency_ms'), 'cpu', d.get('cpu_pct'))
print('open_n', len(p.get('positions') or []))
print('halt', open('/etc/bilshenz.env').read().count('SCANNER_EXEC=0')>0)
"
'''

pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, username="root", pkey=pkey, timeout=40, look_for_keys=False, allow_agent=False)
_, o, e = c.exec_command(CMD, timeout=90)
print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
err=e.read().decode("utf-8", "replace")
if err.strip():
    print(err.encode("ascii", "replace").decode("ascii")[-1500:])
c.close()
