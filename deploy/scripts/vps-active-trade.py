#!/usr/bin/env python3
from pathlib import Path
import paramiko

key = paramiko.Ed25519Key.from_private_key_file(str(Path.home() / ".ssh" / "id_ed25519"))
c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect("159.223.29.223", username="root", pkey=key, timeout=30, look_for_keys=False, allow_agent=False)
CMD = r"""
curl -sS --max-time 12 http://127.0.0.1:8766/health > /tmp/h.json
curl -sS --max-time 12 http://127.0.0.1:8766/api/positions > /tmp/p.json || echo '{"positions":[]}' > /tmp/p.json
curl -sS --max-time 15 http://127.0.0.1:8766/api/scanner/snapshot > /tmp/snap.json
python3 <<'PY'
import json
h=json.load(open('/tmp/h.json')); s=h.get('scanner') or {}
print('mode', h.get('mode'), 'connected', h.get('connected'), 'exec', s.get('can_execute'))
print('active', s.get('active_symbol'), 'pending', s.get('pending_count'), 'strategies', s.get('active_strategies'))
print('last_exec_error', s.get('last_exec_error'))
for e in (s.get('execution_events') or [])[-8:]:
    print('EVT', e.get('symbol'), e.get('side'), e.get('stage'), e.get('leg'), e.get('quantity'), e.get('fill_price') or e.get('error'))
rows=json.load(open('/tmp/snap.json')).get('rows') or []
for r in rows:
    st=r.get('status') or ''
    if st not in ('Scanning',):
        print('ROW', r.get('symbol'), st, '15m=', r.get('pct15m'), 'status_detail=', r.get('detail') or r.get('note') or '')
ps=json.load(open('/tmp/p.json'))
pos=ps.get('positions') or ps if isinstance(ps, list) else ps.get('positions') or []
print('open_positions', len(pos))
for p in pos[:10]:
    print('POS', p.get('symbol'), p.get('positionSide') or p.get('type'), p.get('volume') or p.get('positionAmt'), 'entry', p.get('price_open') or p.get('entryPrice'), 'pnl', p.get('unRealizedProfit') or p.get('profit'))
PY
grep -E 'CETUS|SHORT|filled|submit|Long 1|exec' /var/log/bilshenz/binance-api.log | tail -n 25
"""
_, o, e = c.exec_command(CMD, timeout=60)
print(o.read().decode("utf-8", "replace"))
print(e.read().decode("ascii", "replace")[-500:])
c.close()
