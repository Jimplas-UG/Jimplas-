#!/usr/bin/env python3
"""Deploy 418-login soft fix + slow forward-bot polling on FRA."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for name in ("main.py", "binance_connector.py"):
        sftp.put(str(ROOT / "binance_trading_system/python" / name), f"/opt/bilshenz/binance_trading_system/python/{name}")
    for rel in (
        "frontend/lib/binanceSession.js",
        "frontend/components/BinanceBridgePanel.js",
    ):
        sftp.put(str(ROOT / rel), f"/opt/bilshenz/{rel}")
    sftp.close()

    cmd = r"""
set -e
/opt/bilshenz/binance_trading_system/python/.venv/bin/python -m py_compile \
  /opt/bilshenz/binance_trading_system/python/main.py \
  /opt/bilshenz/binance_trading_system/python/binance_connector.py
# Slow forward-bot bars polling — was hammering Binance into 418.
python3 - <<'PY'
from pathlib import Path
p=Path('/etc/tradingbot.env')
if p.exists():
    lines=[]
    seen=False
    for line in p.read_text().splitlines():
        if line.startswith('FORWARD_POLL_SEC='):
            lines.append('FORWARD_POLL_SEC=120'); seen=True
        else:
            lines.append(line)
    if not seen:
        lines.append('FORWARD_POLL_SEC=120')
    p.write_text('\n'.join(lines)+'\n')
    print('forward_poll=120')
PY
systemctl restart bilshenz-binance-api
systemctl restart bilshenz-forward-bot || true
sleep 6
python3 - <<'PY'
import json, urllib.request
from pathlib import Path
tok=''
for l in Path('/etc/bilshenz.env').read_text().splitlines():
  if l.startswith('BRIDGE_TOKEN='):
    tok=l.split('=',1)[1].strip().strip('"').strip("'")
# clear cool via login soft path: health first
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read().decode())
s=h.get('scanner') or {}
print('health connected', h.get('connected'), 'cool', h.get('rest_cool_s'), 'exec', s.get('can_execute'), 'active', s.get('active_symbol'))
# simulate login with env keys
d={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
  if '=' in l and not l.startswith('#'):
    k,v=l.split('=',1); d[k]=v.strip().strip('"').strip("'")
body=json.dumps({'api_key':d.get('BINANCE_API_KEY',''),'api_secret':d.get('BINANCE_API_SECRET',''),'testnet':True,'auto_detect_env':True}).encode()
req=urllib.request.Request('http://127.0.0.1:8766/api/login', data=body, method='POST', headers={'Content-Type':'application/json','X-Bridge-Token':tok})
try:
  with urllib.request.urlopen(req, timeout=20) as r:
    j=json.loads(r.read().decode())
    print('login_ok', j.get('ok'), 'mode', j.get('mode'), 'can_execute', j.get('can_execute'))
except Exception as e:
  print('login_err', e)
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
PY
"""
    _, o, e = c.exec_command(cmd, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
