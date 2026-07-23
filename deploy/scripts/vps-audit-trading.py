#!/usr/bin/env python3
"""Quick VPS audit: services, positions, scanner blocks, recent errors."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
set -a; . /etc/bilshenz.env; set +a
echo === SERVICES ===
systemctl is-active bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot 2>/dev/null
echo === HEALTH ===
python3 - <<'PY'
import json,urllib.request,os
H={'Authorization':'Bearer '+os.environ.get('DESK_API_KEY','')}
def get(url, headers=None, timeout=15):
  req=urllib.request.Request(url, headers=headers or {})
  with urllib.request.urlopen(req, timeout=timeout) as r:
    return json.loads(r.read().decode())
h=get('http://127.0.0.1:8766/health')
sc=h.get('scanner') or {}; ss=h.get('scanner_stream') or {}
print('conn', h.get('connected'), 'ws', ss.get('ws_connected'), 'ticks', ss.get('ticks_received'),
      'exec', sc.get('can_execute'), 'block', sc.get('exec_block'), 'err', sc.get('last_exec_error'),
      'active', sc.get('active_symbol'), 'pending', sc.get('best_pending'))
pos=get('http://127.0.0.1:8791/v1/binance/api/positions', H)
ps=pos.get('positions') or []
print('POSITIONS', len(ps))
for p in ps[:20]:
  print(' ', p.get('symbol'), p.get('positionSide') or p.get('leg'), p.get('type'),
        'lev', p.get('leverage'), 'xlev', p.get('exchange_leverage'),
        'vol', p.get('volume'), 'entry', p.get('price_open'), 'pnl', p.get('profit'))
snap=get('http://127.0.0.1:8791/v1/binance/api/scanner/snapshot', H)
blocks=snap.get('blocks') or []
print('BLOCKS', len(blocks))
for b in blocks[:10]:
  print(' ', b.get('symbol'), b.get('status'), b.get('legs'))
rows=[r for r in (snap.get('rows') or []) if r.get('status') not in ('Scanning',)]
print('ACTIVE_ROWS', len(rows))
for r in rows[:12]:
  print(' ', r.get('symbol'), r.get('status'), r.get('pctGain'), r.get('retracePct'), r.get('timeframe'))
PY
echo === API LOG ===
journalctl -u bilshenz-binance-api -n 60 --no-pager 2>/dev/null | tr -cd '\11\12\15\40-\176' | tail -n 60
echo === GIT ===
cd /opt/bilshenz && git --no-pager log -1 --oneline
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, stdout, stderr = client.exec_command(CMD, timeout=90)
    sys.stdout.write(stdout.read().decode("utf-8", errors="replace"))
    err = stderr.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err)
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
