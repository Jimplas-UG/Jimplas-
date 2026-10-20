#!/usr/bin/env python3
"""Deploy permanent ops locks: false SHORT_GONE, naked 10x flatten, close bypass, retry drops."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE = "/opt/bilshenz/binance_trading_system/python"
PY = f"{REMOTE}/.venv/bin/python"

FILES = [
    "binance_trading_system/python/binance_connector.py",
    "binance_trading_system/python/momentum_scanner.py",
    "binance_trading_system/python/test_permanent_leak_locks.py",
]

CMD = rf"""
set -e
cd {REMOTE}
{PY} -m py_compile binance_connector.py momentum_scanner.py
{PY} test_permanent_leak_locks.py 2>&1 | tail -n 12
{PY} test_sep23_capital_locks.py 2>&1 | tail -n 8
{PY} - <<'PY'
from frozen_strategy import assert_frozen_contract, STRATEGY_VARIANT, RETRACE_ENTRY_PCT
import momentum_scanner as ms
import inspect
assert STRATEGY_VARIANT == "sep_retrace07"
assert abs(RETRACE_ENTRY_PCT - 0.7) < 1e-9
src = inspect.getsource(ms.MomentumScanner._ensure_pair_coherence)
assert "_force_confirm_short_open" in src
assert "NAKED_LEVERAGE_LOCK" in inspect.getsource(ms.MomentumScanner._manage_positions)
assert "bypass_rest_cool=True" in inspect.getsource(ms.MomentumScanner._close_all)
assert "_snapshot_symbol_legs_to_sticky" in inspect.getsource(ms.MomentumScanner._execute_pending_short)
snap = assert_frozen_contract()
print("PERMANENT_OK", snap["strategy_id"], STRATEGY_VARIANT, "retrace", RETRACE_ENTRY_PCT)
PY
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 10
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
python3 - <<'PY'
import json, time, urllib.request, pathlib
for i in range(25):
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
    sc=h.get('scanner') or {{}}
    print(i, 'can', sc.get('can_execute'), 'tracked', sc.get('symbols_tracked'), 'active', sc.get('active_symbol'), 'cool', h.get('rest_cool_s'))
    if h.get('connected') and sc.get('symbols_tracked', 0) > 50:
        break
    time.sleep(1)
# watch for NAKED_LEVERAGE_LOCK / PHA flatten
time.sleep(8)
since=time.strftime('%Y-%m-%dT%H:%M', time.gmtime(time.time()-120))
hits=[]
with open('/var/log/bilshenz/binance-api.log', errors='replace') as fh:
    for l in fh:
        if l.startswith('2026-') and l[:16] >= since[:16]:
            if 'NAKED_LEVERAGE_LOCK' in l or ('PHAUSDT' in l and ('flatten' in l.lower() or 'SHORT' in l or '5x' in l)):
                hits.append(l.strip()[:200])
print('POST_DEPLOY_HITS', len(hits))
for l in hits[-12:]:
    print(' ', l)
tok=open('/etc/bilshenz.env').read().split('BRIDGE_TOKEN=')[1].splitlines()[0].strip().strip('"').strip("'")
req=urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={{'Authorization':'Bearer '+tok}})
pos=json.loads(urllib.request.urlopen(req, timeout=15).read())
opens=[p for p in (pos.get('positions') or []) if abs(float(p.get('volume') or 0))>1e-12]
print('OPEN_N', len(opens))
for p in opens:
    print('OPEN', p.get('symbol'), p.get('positionSide'), 'ui', p.get('leverage'), 'ex', p.get('exchange_leverage'), 'qty', p.get('volume'))
PY
"""

def main():
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for rel in FILES:
        local = ROOT / rel
        remote = f"/opt/bilshenz/{rel.replace(chr(92), '/')}"
        sftp.put(str(local), remote)
        print("uploaded", rel)
    sftp.close()
    _, o, e = c.exec_command(CMD, timeout=240)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err.encode("ascii", "replace").decode("ascii")[-2500:])
    c.close()

if __name__ == "__main__":
    main()
