#!/usr/bin/env python3
"""Live FRA: running trade vs violation locks / rule kernel."""
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
from pathlib import Path

tok = open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
H = {'Authorization': 'Bearer ' + tok}

def get(url):
    req = urllib.request.Request(url, headers=H)
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode())

h = json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc = h.get('scanner') or {}
pos = get('http://127.0.0.1:8766/api/positions')
items = [p for p in (pos.get('positions') or []) if float(p.get('volume') or p.get('positionAmt') or 0) > 1e-12]
snap = get('http://127.0.0.1:8766/api/scanner/snapshot')

print('=== EXEC ===')
print('can', sc.get('can_execute'), 'halt', sc.get('user_exec_halted'), 'block', sc.get('exec_block'))
print('kernel', sc.get('rule_kernel'))
print('active', sc.get('active_symbol'), 'partition', sc.get('partition_usd'), 'strategy', sc.get('strategy_id'))
print('pair_isolation', json.dumps(h.get('pair_isolation') or {}, default=str)[:500])

print('=== POSITIONS', len(items), '===')
by = {}
for p in items:
    sym = str(p.get('symbol') or '').upper()
    by.setdefault(sym, []).append(p)
    print(json.dumps({
        'symbol': sym,
        'side': p.get('positionSide') or p.get('type'),
        'leg': p.get('leg'),
        'vol': p.get('volume') or p.get('positionAmt'),
        'lev': p.get('leverage'),
        'ex_lev': p.get('exchange_leverage'),
        'policy_lev': p.get('policy_leverage'),
        'margin': p.get('margin_type') or p.get('marginType'),
        'entry': p.get('entryPrice') or p.get('price_open'),
        'mark': p.get('markPrice') or p.get('price_current'),
        'pnl': p.get('profit') if p.get('profit') is not None else p.get('unRealizedProfit'),
    }, default=str))

# scanner row for active
rows = snap.get('rows') or []
active = str(sc.get('active_symbol') or '').upper()
for r in rows:
    if str(r.get('symbol') or '').upper() == active:
        print('SCANNER_ROW', json.dumps({k: r.get(k) for k in (
            'symbol','status','unrealizedPnl','highestPrice','retracePct','pct15m','price'
        )}, default=str))
        break

# violation checks
viol = []
warn = []
for sym, legs in by.items():
    sides = []
    for p in legs:
        ps = str(p.get('positionSide') or '').upper()
        typ = str(p.get('type') or '').upper()
        if ps in ('SHORT','LONG'):
            sides.append(ps)
        elif typ == 'SELL':
            sides.append('SHORT')
        elif typ == 'BUY':
            sides.append('LONG')
    shorts = [p for p in legs if (str(p.get('positionSide') or '').upper()=='SHORT' or str(p.get('type') or '').upper()=='SELL')]
    longs = [p for p in legs if (str(p.get('positionSide') or '').upper()=='LONG' or str(p.get('type') or '').upper()=='BUY')]
    if len(shorts) > 1:
        viol.append(f'OVERLAP_SHORT:{sym} n={len(shorts)}')
    if longs and not shorts:
        viol.append(f'ORPHAN_LONG:{sym}')
    naked = bool(shorts) and not longs
    for p in shorts:
        lev = int(float(p.get('exchange_leverage') or p.get('leverage') or 0) or 0)
        pol = int(float(p.get('policy_leverage') or 0) or 0)
        if naked and lev >= 10:
            viol.append(f'NAKED_SHORT_AT_10X:{sym} lev={lev} policy={pol}')
        elif naked and lev not in (0, 5) and lev > 5:
            viol.append(f'NAKED_SHORT_WRONG_LEV:{sym} lev={lev}')
        if naked and pol and pol != 5:
            warn.append(f'policy_not_5_on_naked:{sym} policy={pol}')
    if shorts and longs:
        # hedged — 10x ok
        for p in shorts + longs:
            lev = int(float(p.get('exchange_leverage') or p.get('leverage') or 0) or 0)
            if lev and lev not in (5, 10):
                warn.append(f'odd_lev_hedged:{sym} lev={lev}')

if sc.get('user_exec_halted') or sc.get('exec_block') == 'EMERGENCY_STOP':
    codes = (sc.get('rule_kernel') or {}).get('halt_codes') or []
    viol.append(f'EMERGENCY_STOP codes={codes}')

# adverse / L1 L2 from position_logic if present
pl = snap.get('position_logic') or {}
print('POSITION_LOGIC', json.dumps(pl, default=str)[:1200] if pl else None)

# recent log hits for active symbol
print('=== VERDICT ===')
print('VIOLATIONS', viol or ['none'])
print('WARNINGS', warn or ['none'])
print('BOOK', 'FLAT' if not items else 'OPEN')
PY

echo '=== LOG (active/watchdog last 40) ==='
ACTIVE=$(python3 -c "import json,urllib.request; h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health',timeout=5).read()); print((h.get('scanner') or {}).get('active_symbol') or '')")
echo ACTIVE=$ACTIVE
if [ -n "$ACTIVE" ]; then
  grep -E "$ACTIVE|RULE_WATCHDOG|RULE_KERNEL|NAKED_SHORT|PARTIAL_CLOSE|ORPHAN|OVERLAP|INVALIDATION|LONG1|LONG2" /var/log/bilshenz/app.log | tail -n 50
else
  grep -E 'RULE_WATCHDOG|RULE_KERNEL|NAKED_SHORT|PARTIAL_CLOSE|ORPHAN' /var/log/bilshenz/app.log | tail -n 30
fi
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=120)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
