#!/usr/bin/env python3
"""Audit scanner rows: status mix, top 15m pumps, history depth."""
from __future__ import annotations

import json
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
set -a; . /etc/bilshenz.env; set +a
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json
curl -sS -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/scanner/snapshot' > /tmp/snap.json
python3 <<'PY'
import json
from collections import Counter
h=json.load(open('/tmp/h.json'))
snap=json.load(open('/tmp/snap.json'))
s=h.get('scanner') or {}
ss=h.get('scanner_stream') or {}
print('stream', {k: ss.get(k) for k in ('ws_connected','rest_active','ticks_received','symbols_subscribed','last_error','last_tick_age_ms')})
print('scanner', {k: s.get(k) for k in ('can_execute','exec_block','pending_count','watchlist','active_symbol','best_pending','risk_locked','entry_tf','min_live_pct','min_retrace','max_retrace')})
rows=snap.get('rows') or []
print('rows', len(rows), 'snap_keys', sorted(snap.keys()))
sts=Counter(str(r.get('status') or '?') for r in rows)
print('status', dict(sts))
# top by pct15m / pctGain
def f(r, *ks):
  for k in ks:
    try:
      v=float(r.get(k) or 0); return v
    except: pass
  return 0.0
ranked=sorted(rows, key=lambda r: max(f(r,'pct15m','pctGain','bestPct'), f(r,'pctGain')), reverse=True)
print('=== top 20 by 15m/gain ===')
for r in ranked[:20]:
  print({
    'sym': r.get('symbol'),
    'st': r.get('status'),
    'pct15m': r.get('pct15m'),
    'pctGain': r.get('pctGain'),
    'best': r.get('bestPct') or r.get('best_pct'),
    'retrace': r.get('retracePct'),
    'tf': r.get('timeframe') or r.get('bestTf'),
    'hist': r.get('historyPoints') or r.get('ticks') or r.get('barCount'),
    'price': r.get('price'),
  })
ge5=sum(1 for r in rows if f(r,'pct15m','pctGain')>=5)
ge3=sum(1 for r in rows if f(r,'pct15m','pctGain')>=3)
ge1=sum(1 for r in rows if f(r,'pct15m','pctGain')>=1)
print('ge5', ge5, 'ge3', ge3, 'ge1', ge1)
# env-ish from health
print('pair', h.get('pair_isolation'))
print('exec_events', (s.get('execution_events') or [])[:5])
# sample raw keys from first row
if rows:
  print('row_keys', sorted(rows[0].keys()))
PY
echo === LOG_TAIL ===
grep -E 'seed|history|kline|REST|scanner SHORT|Pending|demote|WATCH|no symbol|subscribe|universe|SCANNER' /var/log/bilshenz/app.log 2>/dev/null | tail -n 40
echo === JOURNAL ===
journalctl -u bilshenz-binance-api --since '30 min ago' --no-pager -o cat 2>/dev/null | grep -Ei 'seed|history|pending|demote|block|exec|error|SHORT|watch' | tail -n 40
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
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
