#!/usr/bin/env python3
"""Live FRA check after a desk manual close — positions, gates, halt, recent logs."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
import json, urllib.request

tok = open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
H = {'Authorization': 'Bearer ' + tok}

def get(url):
    req = urllib.request.Request(url, headers=H)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

h = json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc = h.get('scanner') or {}
st = get('http://127.0.0.1:8766/api/status')
pos = get('http://127.0.0.1:8766/api/positions')
items = [p for p in (pos.get('positions') or []) if float(p.get('volume') or p.get('positionAmt') or 0) > 1e-12]

print('=== HEALTH ===')
print('connected', h.get('connected'), 'mode', h.get('mode'), 'cool_s', h.get('rest_cool_s'))
print('strategy', sc.get('strategy_id'), 'partition', sc.get('partition_usd'))
print('can_execute', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'), 'block', sc.get('exec_block'), 'active', sc.get('active_symbol'))
print('rule_kernel', sc.get('rule_kernel'))
pi = h.get('pair_isolation') or st.get('pair_isolation')
print('pair_isolation', json.dumps(pi, default=str)[:800] if pi is not None else None)
print('warning', st.get('warning') or st.get('error') or h.get('warning'))
print('balance', (st.get('account') or {}).get('balance'), 'testnet', st.get('testnet'))

print('=== OPEN_POSITIONS', len(items), '===')
for p in items:
    print(
        p.get('symbol'),
        p.get('positionSide') or p.get('type'),
        'vol=', p.get('volume') or p.get('positionAmt'),
        'lev=', p.get('leverage'),
        'pnl=', p.get('profit') if p.get('profit') is not None else p.get('unRealizedProfit'),
        'entry=', p.get('entryPrice') or p.get('price_open'),
    )

# scanner detail from status if present
for k in ('active_symbol', 'active_status', 'watching_count', 'open_symbols', 'legs', 'coins_summary'):
    if sc.get(k) is not None:
        print('scanner', k, sc.get(k))

# try scanner snapshot endpoint if exists
for path in ('/api/scanner/status', '/api/scanner', '/api/momentum'):
    try:
        snap = get('http://127.0.0.1:8766' + path)
        print('endpoint', path, 'keys', list(snap.keys())[:20])
        print(json.dumps(snap, default=str)[:1200])
        break
    except Exception as e:
        print('endpoint', path, 'skip', type(e).__name__)

print('=== VERDICT_HINTS ===')
issues = []
if not h.get('connected'):
    issues.append('not_connected')
if sc.get('user_exec_halted'):
    issues.append('exec_halted')
if not sc.get('can_execute'):
    issues.append('cannot_execute:' + str(sc.get('exec_block')))
cool = float(h.get('rest_cool_s') or 0)
if cool > 0:
    issues.append(f'rest_cool_{cool:.0f}s')
if items:
    # orphan long without short?
    by = {}
    for p in items:
        sym = str(p.get('symbol') or '').upper()
        by.setdefault(sym, []).append(p)
    for sym, legs in by.items():
        sides = []
        for p in legs:
            ps = str(p.get('positionSide') or '').upper()
            typ = str(p.get('type') or '').upper()
            if ps in ('SHORT', 'LONG'):
                sides.append(ps)
            elif typ == 'SELL':
                sides.append('SHORT')
            elif typ == 'BUY':
                sides.append('LONG')
        if 'LONG' in sides and 'SHORT' not in sides:
            issues.append(f'orphan_long:{sym}')
        if len(set(sides)) == 1 and sides[0] == 'SHORT':
            issues.append(f'naked_short_remaining:{sym}')
        if 'SHORT' in sides and 'LONG' in sides:
            issues.append(f'pair_still_open:{sym}')
if pi and isinstance(pi, dict):
    if pi.get('close_all_pending') or pi.get('global_close_all'):
        issues.append('close_all_gate')
    pending = pi.get('close_pending') or pi.get('closing') or pi.get('close_refcount') or {}
    if pending:
        issues.append(f'close_pending:{pending}')
print('ISSUES', issues or ['none'])
print('BOOK', 'FLAT' if not items else 'OPEN')
PY

echo '=== SERVICES ==='
systemctl is-active bilshenz-bridge 2>/dev/null || systemctl is-active bilshenz 2>/dev/null || true
systemctl is-active bilshenz-forward-bot 2>/dev/null || true

echo '=== RECENT LOG HITS ==='
for f in /var/log/bilshenz/bridge.log /var/log/tradingbot/bridge.log /var/log/tradingbot/forward-bot.log /opt/bilshenz/logs/app.log /var/log/bilshenz/app.log; do
  if [ -f "$f" ]; then
    echo "FILE $f"
    grep -E 'CLOSE_|MANUAL_|reconcile|orphan|PARTIAL_CLOSE|EMERGENCY|close_pending|RULE_KERNEL|CLOSE_PENDING|long_residual|pair_isolation|adopt' "$f" | tail -n 50 || true
  fi
done
journalctl -u bilshenz-bridge --since '3 hours ago' --no-pager 2>/dev/null | grep -E 'CLOSE_|MANUAL_|reconcile|orphan|PARTIAL_CLOSE|EMERGENCY|CLOSE_PENDING|long_residual|RULE_KERNEL' | tail -n 60 || true
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, stdout, stderr = client.exec_command(CMD, timeout=120)
    sys.stdout.write(stdout.read().decode("utf-8", "replace"))
    err = stderr.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-2500:])
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
