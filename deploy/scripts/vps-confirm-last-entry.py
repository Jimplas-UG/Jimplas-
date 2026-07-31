#!/usr/bin/env python3
"""Confirm latest scanner primary entry vs short-first rules."""
from __future__ import annotations

import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
set -euo pipefail
set -a; . /etc/bilshenz.env; set +a
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json
curl -sS -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/scanner/snapshot' > /tmp/snap.json || echo '{}' >/tmp/snap.json
curl -sS -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/positions' > /tmp/pos.json || echo '{}' >/tmp/pos.json
curl -sS -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/logs?limit=60' > /tmp/logs.json || echo '{}' >/tmp/logs.json
journalctl -u bilshenz-binance-api --since '4 hours ago' --no-pager > /tmp/j.txt 2>/dev/null || true
python3 <<'PY'
import json, re, time
from datetime import datetime, timezone

h=json.load(open('/tmp/h.json'))
s=h.get('scanner') or {}
print('mode', h.get('mode'), 'connected', h.get('connected'))
print('active', s.get('active_symbol'), 'can_execute', s.get('can_execute'), 'risk_locked', s.get('risk_locked'))
print('partitions', s.get('short_partition_pct'), s.get('long1_partition_pct'), s.get('long2_partition_pct'))
print('=== execution_events ===')
for e in (s.get('execution_events') or [])[:20]:
    print(json.dumps(e, sort_keys=True))

pos=(json.load(open('/tmp/pos.json')).get('positions') or [])
print('=== open_positions ===')
open_syms=set()
for p in pos:
    if float(p.get('volume') or 0) <= 0:
        continue
    sym=str(p.get('symbol') or '').upper()
    open_syms.add(sym)
    print(sym, p.get('positionSide') or p.get('type') or p.get('side'),
          'vol', p.get('volume'), 'entry', p.get('price_open') or p.get('entryPrice'),
          'pnl', p.get('profit') or p.get('unRealizedProfit'), 'lev', p.get('leverage'))

snap=json.load(open('/tmp/snap.json'))
rows={str(r.get('symbol') or '').upper(): r for r in (snap.get('rows') or [])}
for sym in sorted(open_syms) or ([s.get('active_symbol')] if s.get('active_symbol') else []):
    if not sym:
        continue
    r=rows.get(sym) or {}
    print('=== scanner_row', sym, '===')
    print({k:r.get(k) for k in (
        'symbol','status','pctGain','pct15m','pct1m','pct3m','pct5m',
        'retracePct','qualifyingPct','price','bestTf','timeframe')})

logs=json.load(open('/tmp/logs.json'))
deals=logs.get('deals') or []
print('=== recent_deals ===')
for d in deals[:40]:
    print(d.get('time'), d.get('symbol'), d.get('side'), d.get('position_side'),
          'CLOSE' if d.get('is_close') else 'OPEN', 'vol', d.get('volume'),
          'px', d.get('price'), 'pnl', d.get('profit'), 'magic', d.get('magic'),
          'cid', d.get('client_order_id') or d.get('clientOrderId'))

# Parse journal for primary short fills and pending qualify lines
text=open('/tmp/j.txt', encoding='utf-8', errors='replace').read()
pat=re.compile(r'(RIFUSDT|BANKUSDT|scanner SHORT|scanner LONG|Pending|entered|EXEC_|best pending|demote|blocked|qualify|adopted|SHORT failed|LONG1 |LONG2 )')
hits=[ln for ln in text.splitlines() if pat.search(ln)]
print('=== journal_hits', len(hits), '===')
for ln in hits[-100:]:
    print(ln[-420:])

# Focused verdict for active short
active=s.get('active_symbol')
shorts=[p for p in pos if float(p.get('volume') or 0)>0 and str(p.get('positionSide') or p.get('type') or p.get('side') or '').upper() in ('SHORT','SELL')]
longs=[p for p in pos if float(p.get('volume') or 0)>0 and str(p.get('positionSide') or p.get('type') or p.get('side') or '').upper() in ('LONG','BUY')]
print('=== verdict_inputs ===')
print('shorts', [(p.get('symbol'), p.get('volume'), p.get('price_open') or p.get('entryPrice')) for p in shorts])
print('longs', [(p.get('symbol'), p.get('volume'), p.get('price_open') or p.get('entryPrice')) for p in longs])

# Find opening short deal for active
opens=[d for d in deals if not d.get('is_close') and str(d.get('position_side') or '').upper()=='SHORT']
print('short_opens', [(d.get('symbol'), d.get('time'), d.get('price'), d.get('volume'), d.get('client_order_id') or d.get('clientOrderId')) for d in opens[:10]])

# Look for scanner SHORT fill lines
for ln in hits:
    if 'scanner SHORT' in ln and 'qty=' in ln:
        print('FILL_LINE', ln[-300:])
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
    _, o, e = c.exec_command(CMD, timeout=120)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err[-3000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
