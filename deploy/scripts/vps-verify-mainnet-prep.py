#!/usr/bin/env python3
"""Verify mainnet prep + Oct1 wipe on FRA."""
from pathlib import Path
import sys
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
python3 - <<'PY'
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import urllib.request

env={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
  if '=' in l and not l.startswith('#'):
    k,v=l.split('=',1); env[k]=v.strip().strip('"').strip("'")
print('TESTNET', env.get('BINANCE_TESTNET'), 'FORCE_MAIN', env.get('BINANCE_FORCE_MAINNET'), 'FORCE_TN', env.get('BINANCE_FORCE_TESTNET'))
print('TRADE_HISTORY_SINCE', env.get('TRADE_HISTORY_SINCE'))
print('key_len', len(env.get('BINANCE_API_KEY','')))
risk=json.loads(Path('/var/lib/bilshenz/scanner-risk.json').read_text())
print('risk', risk)
cache_path=Path('/var/lib/bilshenz/trade-history-cache.json')
cache=json.loads(cache_path.read_text()) if cache_path.exists() else {}
days=(cache.get('calendar') or {}).get('days') or []
print('cache_cal', [(d.get('date'), d.get('pnl'), d.get('trades')) for d in days])
print('oct1_in_cache', any(d.get('date')=='2026-10-01' for d in days))
deals=cache.get('deals') or []
n=0
for r in deals:
  t=int(r.get('time') or 0)
  if t and t<1e12: t*=1000
  if t:
    utc=datetime.fromtimestamp(t/1000, timezone.utc).strftime('%Y-%m-%d')
    nbo=datetime.fromtimestamp(t/1000, timezone.utc).astimezone(timezone(timedelta(hours=3))).strftime('%Y-%m-%d')
    if utc=='2026-10-01' or nbo=='2026-10-01': n+=1
print('oct1_deals', n, 'deals_total', len(deals))
print('bak_exists', Path('/var/lib/bilshenz/trade-history-cache.pre-mainnet-oct1wipe.json').exists())
tok=env.get('BRIDGE_TOKEN','')
def get(u):
  req=urllib.request.Request(u, headers={'X-Bridge-Token':tok})
  with urllib.request.urlopen(req, timeout=12) as r: return json.loads(r.read().decode())
h=get('http://127.0.0.1:8766/health')
st=get('http://127.0.0.1:8766/api/status')
cal=get('http://127.0.0.1:8766/api/trade-calendar?days=14')
s=h.get('scanner') or {}
print('health_mode', h.get('mode'), 'connected', h.get('connected'))
print('status_mode', st.get('mode'), 'testnet', st.get('testnet'))
err=str(st.get('error') or '')[:160]
print('status_error', err if err else None)
print('partition', s.get('partition_usd'), 'locked', s.get('partition_usd_locked'), 'strategy', s.get('strategy_id'))
print('pct', s.get('short_partition_pct'), s.get('long1_partition_pct'), s.get('long2_partition_pct'))
print('exec', s.get('can_execute'), 'block', s.get('exec_block'))
print('cal_days', [(d.get('date'), d.get('pnl'), d.get('trades')) for d in (cal.get('days') or [])])
print('cal_oct1', [d for d in (cal.get('days') or []) if d.get('date')=='2026-10-01'])
import sys
sys.path.insert(0,'/opt/bilshenz/binance_trading_system/python')
from frozen_strategy import assert_frozen_contract
snap=assert_frozen_contract()
print('ops', snap.get('ops'))
assert float(s.get('partition_usd') or 0)==100.0
assert float(risk.get('partition_usd') or 0)==100.0
assert not any(d.get('date')=='2026-10-01' for d in days)
assert n==0
assert env.get('BINANCE_FORCE_MAINNET')=='1'
assert env.get('BINANCE_TESTNET')=='0'
print('VERIFY_OK')
PY
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=90)
    out = o.read().decode("utf-8", "replace")
    err = e.read().decode("utf-8", "replace")
    sys.stdout.buffer.write(out.encode("utf-8", "replace"))
    if err.strip():
        sys.stderr.buffer.write(b"STDERR " + err[-1500:].encode("utf-8", "replace"))
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
