#!/usr/bin/env python3
"""Diagnose last scanner entry + pending queue blockers."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""#!/usr/bin/env bash
set -euo pipefail
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
echo === HEALTH_SCANNER ===
curl -sS -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json
python3 - <<'PY'
import json
h=json.load(open('/tmp/h.json'))
s=h.get('scanner') or {}
print(json.dumps({
  'mode': h.get('mode'),
  'active': s.get('active_symbol'),
  'pending': s.get('pending_count'),
  'best_pending': s.get('best_pending'),
  'min_live_entry_pct': s.get('min_live_entry_pct'),
  'max_retrace': s.get('max_retrace_entry_pct'),
  'one_trade': s.get('one_trade_at_a_time'),
  'last_exec_error': s.get('last_exec_error'),
  'events': (s.get('execution_events') or [])[:8],
}, indent=2))
PY

echo === SNAPSHOT_ROWS ===
curl -sS -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/scanner/snapshot' > /tmp/snap.json 2>/dev/null || echo '{}' > /tmp/snap.json
python3 - <<'PY'
import json
try:
  j=json.load(open('/tmp/snap.json'))
except Exception as e:
  print('no_snapshot', e); raise SystemExit
if isinstance(j, dict) and j.get('detail'):
  print('snapshot_error', j.get('detail'))
rows=j.get('rows') or []
def key(r):
  st=str(r.get('status') or '')
  return (0 if any(x in st for x in ('Pend','Long','Short','Watch')) else 1, -float(r.get('pct15m') or r.get('pct_15m') or 0))
rows=sorted(rows, key=key)[:15]
for r in rows:
  print({
    'symbol': r.get('symbol'),
    'status': r.get('status'),
    'pct15m': r.get('pct15m', r.get('pct_15m')),
    'retrace': r.get('retracePct', r.get('retrace_pct')),
    'price': r.get('price'),
    'qualifying': r.get('qualifyingPct', r.get('qualifying_pct')),
  })
print('n_rows', len(j.get('rows') or []))
sc=j.get('scanner') or {}
print('meta', {k:sc.get(k) for k in ['pending_count','best_pending','active_symbol','min_live_entry_pct','last_exec_error']})
PY

echo === LOGS_BANK_STORJ ===
journalctl -u bilshenz-binance-api --since '6 hours ago' --no-pager 2>/dev/null | tr -cd '\11\12\15\40-\176\n' | grep -E 'BANKUSDT|STORJUSDT|best pending|LONG1|SHORT1|pending|demote|blocked|EXEC_OK|EXEC_FAIL|scanner LONG|PULLBACK|SMART|orphan|queue' | tail -n 80

echo === APP_LOG ===
tail -n 200 /var/log/tradingbot/binance-api.log 2>/dev/null | tr -cd '\11\12\15\40-\176\n' | grep -E 'BANKUSDT|STORJUSDT|LONG1|SHORT1|pending|blocked|EXEC_|demote' | tail -n 60 || true
ls -lt /var/log/tradingbot 2>/dev/null | head -n 10 || true
ls -lt /var/log/bilshenz 2>/dev/null | head -n 10 || true
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
    print(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        print(err, file=sys.stderr)
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
