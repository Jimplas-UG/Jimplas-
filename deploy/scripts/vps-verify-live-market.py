#!/usr/bin/env python3
"""Follow-up: forward bot + live market after settle; no APK rebuild unless needed."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
set -a; . /etc/bilshenz.env; set +a
echo === services ===
systemctl is-active bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot 2>/dev/null
sleep 50
python3 <<'PY'
import json,urllib.request,os
H={'Authorization':'Bearer '+os.environ.get('DESK_API_KEY','')}

def get(url, headers=None, timeout=30):
  req=urllib.request.Request(url, headers=headers or {})
  try:
    with urllib.request.urlopen(req, timeout=timeout) as r:
      return r.status, json.loads(r.read().decode())
  except Exception as e:
    code=getattr(e,'code',0)
    body=''
    if hasattr(e,'read'):
      try: body=e.read()[:300].decode()
      except: body=str(e)
    return code, {'error': body or str(e)}

code,h=get('http://127.0.0.1:8766/health')
sc=h.get('scanner') or {}; ss=h.get('scanner_stream') or {}
print('HEALTH', code, 'conn', h.get('connected'), 'ws', ss.get('ws_connected'), 'ticks', ss.get('ticks_received'), 'exec', sc.get('can_execute'), sc.get('exec_block'))
code,s=get('http://127.0.0.1:8791/v1/binance/api/scanner/snapshot', H)
rows=s.get('rows') or []
print('ROWS', len(rows))
nonzero24=sum(1 for r in rows if abs(float(r.get('pct24h') or 0))>0.01)
print('nonzero_24h', nonzero24)
for r in rows[:8]:
  print(' ', r.get('symbol'), 'g', r.get('pctGain'), '3m', r.get('pct3m'), '24h', r.get('pct24h'), r.get('status'))
code,t=get('http://127.0.0.1:8791/v1/binance/api/tick/XAUUSDT', H)
print('TICK', code, t if isinstance(t,dict) else t)
code,st=get('http://127.0.0.1:8791/v1/binance/api/status', H)
print('STATUS', code, {k: (st or {}).get(k) for k in ['connected','can_execute','exec_block','mode']})
code,pos=get('http://127.0.0.1:8791/v1/binance/api/positions', H)
print('POS', code, (pos if not isinstance(pos,dict) else {k:pos.get(k) for k in list(pos)[:6]}))
PY
echo === forward ===
systemctl status bilshenz-forward-bot --no-pager -l | head -n 25 | tr -cd '\11\12\15\40-\176'
echo === forward log ===
tail -n 30 /var/log/tradingbot/forward-bot.log 2>/dev/null | tr -cd '\11\12\15\40-\176' | tail -n 30
"""


def main() -> int:
    if not PASSWORD:
        return 1
    import paramiko
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, stdout, stderr = client.exec_command(CMD, timeout=120)
    print(stdout.read().decode("utf-8", errors="replace"))
    err = stderr.read().decode("utf-8", errors="replace")
    if err.strip():
        print(err, file=sys.stderr)
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
