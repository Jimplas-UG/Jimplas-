#!/usr/bin/env python3
"""Audit recent VPS deals vs Long→Short1/Short2 strategy logic."""
from __future__ import annotations

import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
set -a; . /etc/bilshenz.env; set +a
python3 - <<'PY'
import json, urllib.request, os, collections, subprocess
BT=os.environ.get('BRIDGE_TOKEN') or os.environ.get('DESK_API_KEY') or ''
H={'X-Bridge-Token':BT}
def get(u):
  r=urllib.request.Request(u, headers=H)
  return json.loads(urllib.request.urlopen(r, timeout=30).read())
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=10).read())
sc=h.get('scanner') or {}
print('mode', h.get('mode'), 'active', sc.get('active_symbol'), 'err', sc.get('last_exec_error'))
print('pullback', sc.get('long_pullback_pct'), 's1%', sc.get('long1_partition_pct'), 's2%', sc.get('long2_partition_pct'), 'locked', sc.get('risk_locked'))
pos=get('http://127.0.0.1:8766/api/positions').get('positions') or []
print('open', [(p.get('symbol'), p.get('positionSide'), p.get('volume'), p.get('profit')) for p in pos])
deals=get('http://127.0.0.1:8766/api/logs?limit=120').get('deals') or []
closes=[d for d in deals if d.get('is_close')]
long_c=[d for d in closes if str(d.get('position_side') or '').upper()=='LONG']
short_c=[d for d in closes if str(d.get('position_side') or '').upper()=='SHORT']
print('closes', len(closes), 'long', len(long_c), 'short', len(short_c))
print('long_pnl', round(sum(float(d.get('profit') or 0) for d in long_c),2), 'short_pnl', round(sum(float(d.get('profit') or 0) for d in short_c),2))
by_sym=collections.defaultdict(list)
for d in sorted(deals, key=lambda x: int(x.get('time') or 0)):
  by_sym[d.get('symbol')].append(d)
stacks=0
for sym, rows in by_sym.items():
  ol=0
  for d in rows:
    ps=str(d.get('position_side') or '').upper()
    if (not d.get('is_close')) and ps=='LONG':
      ol += 1
      if ol>1:
        stacks += 1
        print('STACK', sym, 'n', ol, 'vol', d.get('volume'))
    if d.get('is_close') and ps=='LONG':
      ol=max(0, ol-1)
print('stack_events', stacks)
print('recent_closes:')
for d in closes[:20]:
  print(' ', d.get('symbol'), d.get('position_side'), 'pnl', round(float(d.get('profit') or 0),3), 'vol', d.get('volume'))
wins=[d for d in long_c if float(d.get('profit') or 0)>1]
scratch=[d for d in long_c if -3 <= float(d.get('profit') or 0) < 0]
big=[d for d in long_c if float(d.get('profit') or 0)>50]
print('long_wins>1', len(wins), 'scratches_-3..0', len(scratch), 'big>50', [(d.get('symbol'), round(float(d.get('profit') or 0),1)) for d in big])
cal=get('http://127.0.0.1:8766/api/trade-calendar?days=3')
print('cal', [(x.get('date'), x.get('pnl'), x.get('trades')) for x in (cal.get('days') or [])[-3:]])
print(subprocess.check_output('cd /opt/bilshenz && git log -1 --oneline', shell=True, text=True).strip())
PY
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[:2000])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
