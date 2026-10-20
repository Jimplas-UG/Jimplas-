#!/usr/bin/env python3
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
CMD = r"""
cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python - <<'PY'
import inspect, momentum_scanner as ms
from frozen_strategy import assert_frozen_contract, STRATEGY_VARIANT, RETRACE_ENTRY_PCT
src = inspect.getsource(ms.MomentumScanner._ensure_pair_coherence)
print('force_confirm', '_force_confirm_short_open' in src)
print('close_bypass', 'bypass_rest_cool=True' in inspect.getsource(ms.MomentumScanner._close_all))
short_src = inspect.getsource(ms.MomentumScanner._execute_pending_short)
print('snapshot', '_snapshot_symbol_legs_to_sticky' in short_src)
print('prep5x', 'leverage_5x_prepare_failed' in short_src)
print('naked_lock', 'NAKED_LEVERAGE_LOCK' in inspect.getsource(ms.MomentumScanner._manage_positions))
assert STRATEGY_VARIANT == 'sep_retrace07' and abs(RETRACE_ENTRY_PCT - 0.7) < 1e-9
assert_frozen_contract()
print('MARKERS_OK')
PY
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 12
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
python3 - <<'PY'
import json, time, urllib.request
for i in range(20):
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
    sc=h.get('scanner') or {}
    print(i, 'can', sc.get('can_execute'), 'tracked', sc.get('symbols_tracked'), 'active', sc.get('active_symbol'))
    if h.get('connected') and sc.get('symbols_tracked', 0) > 50:
        break
    time.sleep(1)
tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
req=urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={'Authorization':'Bearer '+tok})
pos=json.loads(urllib.request.urlopen(req, timeout=15).read())
opens=[p for p in (pos.get('positions') or []) if abs(float(p.get('volume') or 0)) > 1e-12]
print('OPEN_N', len(opens))
for p in opens:
    print('OPEN', p.get('symbol'), p.get('positionSide'), 'ui', p.get('leverage'), 'ex', p.get('exchange_leverage'))
time.sleep(20)
since=time.strftime('%Y-%m-%dT%H:%M', time.gmtime(time.time()-120))
print('LOG_SINCE', since)
with open('/var/log/bilshenz/binance-api.log', errors='replace') as fh:
    for l in fh:
        if not (l.startswith('2026-') and l[:16] >= since[:16]):
            continue
        if any(x in l for x in ('NAKED_LEVERAGE', 'SHORT_GONE deferred', 'force confirm', 'sticky-empty', 'leverage_5x')):
            print(l.strip()[:240])
# re-check opens after manage ticks
pos=json.loads(urllib.request.urlopen(req, timeout=15).read())
opens=[p for p in (pos.get('positions') or []) if abs(float(p.get('volume') or 0)) > 1e-12]
print('OPEN_N_AFTER', len(opens))
for p in opens:
    print('OPEN', p.get('symbol'), p.get('positionSide'), 'ui', p.get('leverage'), 'ex', p.get('exchange_leverage'))
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=180)
    print(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err[-2000:])
    c.close()

if __name__ == "__main__":
    main()
