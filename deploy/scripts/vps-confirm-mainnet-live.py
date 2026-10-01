#!/usr/bin/env python3
"""Confirm FRA is live on mainnet with $50 partition — read-only."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set -e
python3 <<'PY'
from pathlib import Path
d={}
for line in Path('/etc/bilshenz.env').read_text().splitlines():
    if '=' in line and not line.startswith('#'):
        k,v=line.split('=',1)
        d[k]=v.strip().strip('"').strip("'")
print(
    'ENV',
    'TESTNET=' + d.get('BINANCE_TESTNET','?'),
    'FORCE_MAIN=' + d.get('BINANCE_FORCE_MAINNET','?'),
    'FORCE_TN=' + d.get('BINANCE_FORCE_TESTNET','?'),
    'PAPER=' + d.get('BINANCE_PAPER','?'),
    'DRY=' + d.get('FORWARD_DRY_RUN','?'),
    'EXEC=' + d.get('SCANNER_EXEC','?'),
    'key_len=' + str(len(d.get('BINANCE_API_KEY',''))),
)
Path('/tmp/tok').write_text(d.get('BRIDGE_TOKEN',''))
PY
TOKEN=$(cat /tmp/tok)
curl -sS -o /dev/null -w 'mainnet_ping=%{http_code}\n' --max-time 10 https://fapi.binance.com/fapi/v1/ping
systemctl is-active bilshenz-binance-api
curl -sS --max-time 12 http://127.0.0.1:8766/health > /tmp/h.json
curl -sS --max-time 15 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/status > /tmp/st.json || echo '{}' > /tmp/st.json
curl -sS --max-time 12 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/api/positions > /tmp/pos.json || echo '{}' > /tmp/pos.json
python3 <<'PY'
import json, subprocess
from pathlib import Path
h=json.loads(Path('/tmp/h.json').read_text() or '{}')
st=json.loads(Path('/tmp/st.json').read_text() or '{}')
pos=json.loads(Path('/tmp/pos.json').read_text() or '{}')
s=h.get('scanner') or {}
acct=st.get('account') or {}
print('--- LIVE CHECK ---')
print('systemd', subprocess.check_output(['systemctl','is-active','bilshenz-binance-api'], text=True).strip())
print('health_ok', h.get('ok'), 'mode', h.get('mode'), 'testnet_flag', h.get('testnet'), 'connected', h.get('connected'), 'cool', h.get('rest_cool_s'))
print('status_mode', st.get('mode'), 'testnet', st.get('testnet'), 'connected', st.get('connected'), 'server', acct.get('server'))
print('balance', acct.get('balance'), 'equity', acct.get('equity'), 'float', acct.get('profit'))
if st.get('error'): print('status_error', str(st.get('error'))[:200])
if st.get('warning'): print('status_warning', str(st.get('warning'))[:140])
print('strategy', s.get('strategy_id'), '|', s.get('strategy_name'))
print('partition_usd', s.get('partition_usd'), 'locked', s.get('risk_locked'), 'pct', s.get('short_partition_pct'), s.get('long1_partition_pct'), s.get('long2_partition_pct'))
print('can_execute', s.get('can_execute'), 'exec_enabled', s.get('exec_enabled'), 'block', s.get('exec_block'), 'halted', s.get('user_exec_halted'))
print('watchlist', s.get('watchlist'), 'pending', s.get('pending_count'), 'active_symbol', s.get('active_symbol'))
print('positions_n', len(pos.get('positions') or []), 'pos_ok', pos.get('ok'), 'stale', pos.get('stale'))
print('risk_file', Path('/var/lib/bilshenz/scanner-risk.json').read_text().strip().replace('\n',' '))
log=subprocess.check_output(
    ['bash','-lc',"grep -E 'fstream.binance.com|stream.binancefuture.com|Bilshenz env=|FORCE_MAINNET|invalid api' /var/log/bilshenz/binance-api.log | tail -n 12"],
    text=True, stderr=subprocess.DEVNULL,
)
print('--- recent log ---')
print(log.strip())
mainnet_ok = (
    str(h.get('mode')).lower() in ('live','mainnet')
    and st.get('testnet') is False
    and float(s.get('partition_usd') or 0) == 100.0
    and s.get('strategy_id') == 'short_first_v1'
    and s.get('can_execute') is True
)
print('VERDICT_MAINNET_LIVE', mainnet_ok)
if st.get('error'):
    print('VERDICT_KEYS', 'FAIL')
elif acct.get('balance') is not None:
    print('VERDICT_KEYS', 'OK')
else:
    print('VERDICT_KEYS', 'UNKNOWN')
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
        sys.stderr.buffer.write(err[-1500:].encode("utf-8", "replace"))
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
