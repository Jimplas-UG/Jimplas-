#!/usr/bin/env python3
"""Wipe Oct 1 testnet history, pin $100, prepare FRA for mainnet live. No strategy changes."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set -euo pipefail

echo '=== 1) WIPE Oct 1 from trade-history-cache (deals + calendar) ==='
python3 <<'PY'
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

DAY = '2026-10-01'
# Desk TZ Africa/Nairobi = UTC+3 — wipe UTC and Nairobi calendar day Oct 1
path = Path('/var/lib/bilshenz/trade-history-cache.json')
bak = Path('/var/lib/bilshenz/trade-history-cache.pre-mainnet-oct1wipe.json')

if path.exists():
    raw = json.loads(path.read_text() or '{}')
    bak.write_text(json.dumps(raw, indent=2))
    print('backup', bak, 'bytes', bak.stat().st_size)
else:
    raw = {'v': 1}
    print('no_cache_yet')

deals = list(raw.get('deals') or [])
kept = []
removed = 0
for r in deals:
    if not isinstance(r, dict):
        continue
    try:
        t = int(r.get('time') or 0)
    except Exception:
        kept.append(r); continue
    if t and t < 1e12:
        t *= 1000
    if not t:
        kept.append(r); continue
    utc_day = datetime.fromtimestamp(t/1000, timezone.utc).strftime('%Y-%m-%d')
    nbo_day = datetime.fromtimestamp(t/1000, timezone.utc).astimezone(timezone(timedelta(hours=3))).strftime('%Y-%m-%d')
    if utc_day == DAY or nbo_day == DAY:
        removed += 1
        continue
    kept.append(r)

cal = raw.get('calendar') if isinstance(raw.get('calendar'), dict) else {}
days = list(cal.get('days') or [])
new_days = []
cal_removed = 0
for row in days:
    if str(row.get('date') or '') == DAY:
        cal_removed += 1
        continue
    new_days.append(row)
total = round(sum(float(x.get('pnl') or 0) for x in new_days), 2)
cal = dict(cal)
cal['days'] = new_days
cal['total_pnl'] = total

out = {
    'v': int(raw.get('v') or 1),
    'deals': kept[:200],
    'calendar': cal,
}
if raw.get('deal_symbols') is not None:
    out['deal_symbols'] = raw.get('deal_symbols')
path.parent.mkdir(parents=True, exist_ok=True)
tmp = path.with_suffix('.json.tmp')
tmp.write_text(json.dumps(out, separators=(',', ':')))
tmp.chmod(0o600)
tmp.replace(path)
print('deals_before', len(deals), 'after', len(kept), 'removed', removed)
print('cal_days_removed', cal_removed, 'cal_days_left', len(new_days), 'total_pnl', total)
print('WIPE_OK')
PY

echo '=== 2) PIN risk $100 + 50/40/40 ==='
python3 <<'PY'
import json
from pathlib import Path
p = Path('/var/lib/bilshenz/scanner-risk.json')
raw = {}
if p.exists():
    try: raw = json.loads(p.read_text() or '{}')
    except: raw = {}
raw.update({
  'partition_usd': 100.0,
  'short_pct': 50.0,
  'long1_pct': 40.0,
  'long2_pct': 40.0,
  'locked': True,
  'partition_usd_locked': True,
  'exec_halted': bool(raw.get('exec_halted', False)),
})
p.write_text(json.dumps(raw, indent=2) + '\n')
p.chmod(0o600)
print('RISK', raw)
PY

echo '=== 3) ENV ready for MAINNET (session cleared; app must login with mainnet keys) ==='
python3 <<'PY'
from pathlib import Path
p = Path('/etc/bilshenz.env')
want = {
  'BINANCE_TESTNET': '0',
  'BINANCE_FORCE_TESTNET': '0',
  'BINANCE_FORCE_MAINNET': '1',
  'BINANCE_PAPER': '0',
  'FORWARD_DRY_RUN': '0',
  'SCANNER_EXEC': '1',
  'SCANNER_ENABLED': '1',
  # Hide any residual pre-live calendar noise; live income starts fresh on mainnet keys.
  'TRADE_HISTORY_SINCE': '2026-10-01',
}
lines = p.read_text().splitlines()
out, seen = [], set()
for line in lines:
    if '=' in line and not line.startswith('#'):
        k = line.split('=', 1)[0]
        if k in want:
            out.append(f'{k}={want[k]}')
            seen.add(k)
            continue
    out.append(line)
for k, v in want.items():
    if k not in seen:
        out.append(f'{k}={v}')
p.write_text('\n'.join(out) + '\n')
p.chmod(0o600)
d = {}
for line in p.read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        a,b=line.split('=',1); d[a]=b.strip().strip('"').strip("'")
print('BINANCE_TESTNET', d.get('BINANCE_TESTNET'))
print('BINANCE_FORCE_MAINNET', d.get('BINANCE_FORCE_MAINNET'))
print('BINANCE_FORCE_TESTNET', d.get('BINANCE_FORCE_TESTNET'))
print('TRADE_HISTORY_SINCE', d.get('TRADE_HISTORY_SINCE'))
print('key_len', len(d.get('BINANCE_API_KEY','')), 'secret_len', len(d.get('BINANCE_API_SECRET','')))
print('NOTE: env keys may still be testnet — phone must Connect with MAINNET Futures keys')
PY

rm -f /var/lib/bilshenz/binance-session.json \
      /opt/bilshenz/binance_trading_system/python/.binance_session.json 2>/dev/null || true
echo 'session_cleared'

systemctl restart bilshenz-binance-api
sleep 10
systemctl is-active bilshenz-binance-api

echo '=== 4) VERIFY locks + mode ==='
TOKEN=$(python3 -c "from pathlib import Path; d={};
[d.__setitem__(a,b.strip().strip(chr(34)).strip(chr(39))) for a,b in (l.split('=',1) for l in Path('/etc/bilshenz.env').read_text().splitlines() if '=' in l and not l.startswith('#'))];
print(d.get('BRIDGE_TOKEN',''))")
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json || true
curl -sS --max-time 15 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/status > /tmp/st.json || true
curl -sS --max-time 15 -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/trade-calendar?days=14' > /tmp/cal.json || true
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/deals?limit=50' > /tmp/deals.json || true

python3 <<'PY'
import json, sys
from pathlib import Path
sys.path.insert(0, '/opt/bilshenz/binance_trading_system/python')
from frozen_strategy import assert_frozen_contract
snap = assert_frozen_contract()
print('CONTRACT', snap['strategy_id'], snap.get('ops'))

h=json.loads(Path('/tmp/h.json').read_text() or '{}')
st=json.loads(Path('/tmp/st.json').read_text() or '{}')
cal=json.loads(Path('/tmp/cal.json').read_text() or '{}')
deals_body=json.loads(Path('/tmp/deals.json').read_text() or '{}')
s=h.get('scanner') or {}
acct=st.get('account') or {}
print('mode', h.get('mode'), 'status_mode', st.get('mode'), 'testnet', st.get('testnet'), 'connected', h.get('connected') or st.get('connected'))
print('partition', s.get('partition_usd'), 'locked', s.get('partition_usd_locked'), s.get('risk_locked'))
print('pct', s.get('short_partition_pct'), s.get('long1_partition_pct'), s.get('long2_partition_pct'))
print('exec', s.get('can_execute'), 'block', s.get('exec_block'))
print('bal', acct.get('balance'), 'server', acct.get('server'))
if st.get('error'): print('status_error', str(st.get('error'))[:180])

oct1 = [d for d in (cal.get('days') or []) if str(d.get('date')) == '2026-10-01']
print('calendar_oct1', oct1)
print('calendar_days', [(d.get('date'), d.get('pnl'), d.get('trades')) for d in (cal.get('days') or [])[-8:]])
rows = deals_body.get('deals') or deals_body.get('history') or (deals_body if isinstance(deals_body, list) else [])
print('deals_api_n', len(rows) if isinstance(rows, list) else type(rows))

risk=json.loads(Path('/var/lib/bilshenz/scanner-risk.json').read_text())
cache=json.loads(Path('/var/lib/bilshenz/trade-history-cache.json').read_text())
cache_oct1_days=[x for x in (cache.get('calendar') or {}).get('days') or [] if x.get('date')=='2026-10-01']
print('disk_risk_partition', risk.get('partition_usd'), 'disk_oct1_cal', cache_oct1_days)

assert float(s.get('partition_usd') or 0) == 100.0
assert float(risk.get('partition_usd') or 0) == 100.0
assert not cache_oct1_days, cache_oct1_days
assert abs(float(snap['ops']['partition_usd']) - 100) < 1e-9
assert snap['ops']['close_rest_cool_max_wait_s'] == 12.0
print('PREP_MAINNET_OK partition=$100 oct1_wiped locks_intact')
print('NEXT: open app → Mainnet → paste MAINNET Futures keys → Connect Binance')
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=180)
    import sys
    sys.stdout.buffer.write(o.read())
    err = e.read()
    if err.strip():
        sys.stderr.buffer.write(b"STDERR " + err[-2000:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
