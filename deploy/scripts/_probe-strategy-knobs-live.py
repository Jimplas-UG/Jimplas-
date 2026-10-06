#!/usr/bin/env python3
"""Read-only FRA probe: strategy knobs + why entries blocked."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
from frozen_strategy import assert_frozen_contract
import momentum_scanner as ms
import inspect, json, urllib.request
snap = assert_frozen_contract()
e, r, t, o, p = snap['entry'], snap['recovery'], snap['tp'], snap['ops'], snap['primary']
print('ID', snap['strategy_id'])
print('KNOBS gain', e['gain_pct'], 'retrace', e['retrace_pct'], 'L1', r['adverse1_pct'], 'L2', r['adverse2_pct'], 'inv', r['invalidation_pct'])
print('KNOBS tp', t['short_pct'], 'smart', o['smart_exit_net_pct'], 'part', o['partition_usd'], 'lev', p['leverage'], r['leverage'])
print('SCANNER', ms.GAIN_THRESHOLD_PCT, ms.RETRACE_ENTRY_PCT, ms.LONG1_ADVERSE_PCT, ms.LONG2_ADVERSE_PCT, ms.PAIR_INVALIDATION_PCT, ms.SHORT_TP_PCT, ms.SMART_EXIT_NET_PCT, ms.LOCKED_PARTITION_USD)
src = inspect.getsource(ms.MomentumScanner._manage_positions)
print('NAKED_FORCE_10X', 'target = LONG1_LEVERAGE' in src)
print('SOLO_HEDGE', hasattr(ms.MomentumScanner, '_solo_hedge_exit_allowed'))
h = json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read())
sc = h.get('scanner') or {}
keys = sorted([k for k in sc.keys() if any(x in k.lower() for x in ('safe','halt','stuck','oversize','can_','part','exec','mode','reason','code'))])
print('LIVE mode', h.get('mode'), 'conn', h.get('connected'))
for k in keys:
    print(' ', k, '=', sc.get(k))
print('PROBE_OK')
PY
"""


def main() -> None:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=60)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("ERR", err.encode("ascii", "replace").decode("ascii")[-800:])
    c.close()


if __name__ == "__main__":
    main()
