#!/usr/bin/env python3
"""Diagnose testnet scanner execution readiness on FRA."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    CMD = r"""
set -e
echo '=== ENV ==='
grep -E '^(BINANCE_TESTNET|BINANCE_FORCE_TESTNET|SCANNER_EXEC|FORWARD_DRY_RUN|BINANCE_PAPER|RISK_PCT|PARTITION)=' /etc/bilshenz.env || true
echo '=== HEALTH ==='
curl -sS --max-time 12 http://127.0.0.1:8766/health > /tmp/h.json
python3 <<'PY'
import json
d=json.load(open('/tmp/h.json'))
s=d.get('scanner') or {}
print('mode', d.get('mode'), 'connected', d.get('connected'))
print('can_execute', s.get('can_execute'), 'exec_enabled', s.get('exec_enabled'), 'block', s.get('exec_block'))
print('risk_locked', s.get('risk_locked'), 'active', s.get('active_symbol'), 'pending', s.get('pending_count'), 'watchlist', s.get('watchlist'), 'strategies', s.get('active_strategies'))
print('tracked', s.get('symbols_tracked'), 'partition_usd', s.get('partition_usd'))
print('last_exec_error', s.get('last_exec_error'))
print('strategy', s.get('strategy_id'))
ev=s.get('execution_events') or []
print('events', len(ev))
for e in ev[-5:]:
    print(' ', e.get('symbol'), e.get('stage'), e.get('error') or e.get('leg'))
PY
echo '=== STATUS ==='
curl -sS --max-time 12 http://127.0.0.1:8766/api/status 2>/dev/null | python3 -c "import sys,json;d=json.load(sys.stdin);print({k:d.get(k) for k in ['ok','connected','testnet','mode','balance','equity','can_trade','error','message'] if k in d or True})" 2>/dev/null || true
curl -sS --max-time 12 http://127.0.0.1:8766/api/status > /tmp/st.json 2>/dev/null || echo '{}' > /tmp/st.json
python3 -c "import json;d=json.load(open('/tmp/st.json')); print('status keys', sorted(d.keys())[:30]); print('testnet', d.get('testnet'), 'bal', d.get('balance') or d.get('account',{}).get('balance') if isinstance(d.get('account'),dict) else d.get('balance'))"
echo '=== SNAPSHOT ==='
curl -sS --max-time 15 http://127.0.0.1:8766/api/scanner/snapshot > /tmp/snap.json || true
python3 <<'PY'
import json
try:
  d=json.load(open('/tmp/snap.json'))
except Exception as e:
  print('snap fail', e); raise SystemExit
s=d.get('scanner') or d
rows=d.get('rows') or []
print('snap ok', d.get('ok'), 'rows', len(rows))
print('can_execute', s.get('can_execute'), 'block', s.get('exec_block'), 'risk_locked', s.get('risk_locked'))
# pending/watching
from collections import Counter
c=Counter((r.get('status') or '?') for r in rows)
print('status_counts', dict(c.most_common(12)))
for r in rows:
  if (r.get('status') or '') in ('Pending','Watching') or r.get('active'):
    print('ROW', r.get('symbol'), r.get('status'), 'pct15', r.get('pct15m'), 'gain', r.get('pctGain'))
PY
echo '=== LOG ==='
grep -E 'exec|EXEC|risk_locked|can_execute|testnet|SHORT|insufficient|block|partition' /var/log/bilshenz/binance-api.log 2>/dev/null | tail -n 40
"""
    _, o, e = c.exec_command(CMD, timeout=90)
    print(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        print("STDERR", err[-1500:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
