#!/usr/bin/env python3
"""Investigate strategy drift vs slow market / cool misses — read-only."""
from __future__ import annotations

import json
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set +e
cd /opt/bilshenz/binance_trading_system/python
echo '=== FROZEN CONTRACT ==='
python3 - <<'PY'
try:
    from frozen_strategy import assert_frozen_contract
    snap = assert_frozen_contract()
    print('CONTRACT_OK', snap['strategy_id'], snap['entry'], snap['tp'])
    print('primary', snap['primary'])
    print('recovery', {k: snap['recovery'][k] for k in ('partition_pct','leverage','adverse1_pct','adverse2_pct','invalidation_pct')})
except Exception as e:
    print('CONTRACT_FAIL', type(e).__name__, e)
PY

echo '=== LIVE THRESHOLDS ==='
python3 - <<'PY'
import momentum_scanner as ms
import os
keys = [
 'GAIN_THRESHOLD_PCT','RETRACE_ENTRY_PCT','MIN_LIVE_ENTRY_PCT','MIN_LIVE_VS_LATCH_FRAC',
 'LONG1_ADVERSE_PCT','LONG2_ADVERSE_PCT','SHORT_TP_PCT','LONG_TP_PCT',
 'LONG_HEDGE_PULLBACK_PCT','SHORT_TRAIL_PULLBACK_PCT','PAIR_INVALIDATION_PCT',
 'HEDGE_RESCUE_BUFFER_PCT','SHORT_PARTITION_PCT','LONG1_PARTITION_PCT','LONG2_PARTITION_PCT',
]
for k in keys:
    print(f'{k}={getattr(ms,k,None)}')
print('env SCANNER_GAIN_PCT', os.environ.get('SCANNER_GAIN_PCT'))
print('env SCANNER_MIN_LIVE_ENTRY_PCT', os.environ.get('SCANNER_MIN_LIVE_ENTRY_PCT'))
print('env BINANCE_TESTNET', os.environ.get('BINANCE_TESTNET'))
print('env BINANCE_FORCE_TESTNET', os.environ.get('BINANCE_FORCE_TESTNET'))
print('env BINANCE_FORCE_MAINNET', os.environ.get('BINANCE_FORCE_MAINNET'))
PY

echo '=== ENV FLAGS ==='
grep -E '^(BINANCE_|SCANNER_|FORWARD_|PARTITION)' /etc/bilshenz.env | sort

echo '=== HEALTH / SCANNER ==='
TOKEN=$(grep '^BRIDGE_TOKEN=' /etc/bilshenz.env | cut -d= -f2-)
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json
python3 - <<'PY'
import json
d=json.load(open('/tmp/h.json'))
s=d.get('scanner') or {}
print('mode', d.get('mode'), 'connected', d.get('connected'), 'testnet', d.get('testnet'))
print('strategy', s.get('strategy_id') or s.get('strategy'))
print('can_execute', s.get('can_execute'), 'block', s.get('exec_block'))
print('partition_usd', s.get('partition_usd'), 'tracked', s.get('tracked'))
print('active', s.get('active'), 'pending', s.get('pending'), 'watchlist', s.get('watchlist'))
print('last_exec_error', s.get('last_exec_error'))
print('rest_cool', d.get('rest_cool_s') or d.get('rest_cooling_s') or s.get('rest_cool_s'))
# top movers by gain / pct15
rows = s.get('rows') or s.get('coins') or []
if not rows:
    # try snapshot endpoint
    pass
print('health_rows', len(rows) if isinstance(rows, list) else type(rows))
PY

curl -sS --max-time 15 -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/scanner/snapshot' > /tmp/snap.json
python3 - <<'PY'
import json
d=json.load(open('/tmp/snap.json'))
rows=d.get('rows') or d.get('coins') or []
print('snap_ok', d.get('ok'), 'rows', len(rows))
print('can_execute', d.get('can_execute'), 'block', d.get('exec_block') or d.get('block'))
# status histogram
from collections import Counter
st=Counter(str(r.get('status') or r.get('state') or '?') for r in rows)
print('status', dict(st))
# sort by gain / pct15
def g(r):
    for k in ('gain_pct','gain','pct15','change_15m','pct_15m'):
        try:
            v=float(r.get(k))
            if v==v: return v
        except Exception:
            pass
    return -999
top=sorted(rows, key=g, reverse=True)[:12]
print('TOP_GAIN')
for r in top:
    print(r.get('symbol') or r.get('coin'), 'status', r.get('status'), 'gain', g(r), 'retrace', r.get('retrace_pct') or r.get('retrace'), 'pct15', r.get('pct15') or r.get('change_15m'))
hot=[r for r in rows if g(r) >= 5.0]
print('hot_ge_5pct', len(hot), [r.get('symbol') or r.get('coin') for r in hot[:15]])
near=[r for r in rows if 3.0 <= g(r) < 5.0]
print('near_3_to_5', len(near), [(r.get('symbol') or r.get('coin'), round(g(r),2)) for r in near[:15]])
watching=[r for r in rows if str(r.get('status')) in ('Watching','watching')]
print('watching', len(watching))
for r in watching[:10]:
    print(' W', r.get('symbol'), 'gain', g(r), 'retrace', r.get('retrace_pct') or r.get('retrace'))
PY

echo '=== RECENT EXEC / COOL MISSES ==='
grep -E 'EXEC_OK|EXEC_FAIL|scanner SHORT|scanner entry|cooling \(418\)|GAIN|retrace|SHORT CELO|SHORT US|SHORT Q' /var/log/bilshenz/binance-api.log 2>/dev/null | tail -n 80

echo '=== TODAY COUNTS ==='
python3 - <<'PY'
from pathlib import Path
from collections import Counter
p=Path('/var/log/bilshenz/binance-api.log')
text=p.read_text(errors='replace') if p.exists() else ''
# rough day filter: today's date in log
import datetime
day=datetime.datetime.utcnow().strftime('%Y-%m-%d')
lines=[ln for ln in text.splitlines() if day in ln or '2026-09-29' in ln]
c=Counter()
for ln in lines:
    if 'EXEC_OK' in ln and 'SELL' in ln: c['short_ok'] += 1
    if 'EXEC_OK' in ln and 'BUY' in ln: c['long_ok'] += 1
    if 'EXEC_FAIL' in ln and 'cooling' in ln: c['fail_cool'] += 1
    if 'EXEC_FAIL' in ln and 'cooling' not in ln: c['fail_other'] += 1
    if 'scanner SHORT' in ln and 'failed' in ln: c['short_failed'] += 1
    if 'scanner SHORT ' in ln and 'failed' not in ln and 'qty=' in ln: c['short_opened'] += 1
    if 'MANUAL_SHORT_FLATTEN' in ln: c['manual_flatten'] += 1
    if 'entry cooldown' in ln: c['entry_cooldown'] += 1
print('counts_today', dict(c))
print('log_lines_today', len(lines))
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=120)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR:", err[-2000:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
