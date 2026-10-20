#!/usr/bin/env python3
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

CMD = r"""
set -e
cd /opt/bilshenz/binance_trading_system/python
rm -rf __pycache__
.venv/bin/python - <<'PY'
import inspect, momentum_scanner as ms, binance_connector as bc
from frozen_strategy import assert_frozen_contract, STRATEGY_VARIANT, RETRACE_ENTRY_PCT
s = inspect.getsource(ms.MomentumScanner._try_open_short_entry)
assert '_snapshot_symbol_legs_to_sticky' in s
assert 'leverage_5x_prepare_failed' in s
assert 'NAKED_LEVERAGE_LOCK' in inspect.getsource(ms.MomentumScanner._manage_positions)
assert '_force_confirm_short_open' in inspect.getsource(ms.MomentumScanner._ensure_pair_coherence)
assert 'bypass_rest_cool=True' in inspect.getsource(ms.MomentumScanner._close_all)
assert 'remote end closed' in inspect.getsource(bc.BinanceConnector._parse_order_error).lower()
assert STRATEGY_VARIANT == 'sep_retrace07' and abs(RETRACE_ENTRY_PCT - 0.7) < 1e-9
assert_frozen_contract()
print('ALL_MARKERS_OK sep_retrace07')
PY
.venv/bin/python test_permanent_leak_locks.py 2>&1 | tail -n 4
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 10
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
python3 - <<'PY'
import json, time, urllib.request
for i in range(20):
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
    sc=h.get('scanner') or {}
    print(i, 'can', sc.get('can_execute'), 'tracked', sc.get('symbols_tracked'), 'cool', h.get('rest_cool_s'))
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
print('LIVE_OK')
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in [
        "binance_trading_system/python/momentum_scanner.py",
        "binance_trading_system/python/binance_connector.py",
        "binance_trading_system/python/test_permanent_leak_locks.py",
    ]:
        sftp.put(str(ROOT / rel), f"/opt/bilshenz/{rel.replace(chr(92), '/')}")
        print("uploaded", rel)
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=180)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err.encode("ascii", "replace").decode("ascii")[-2000:])
    c.close()

if __name__ == "__main__":
    main()
