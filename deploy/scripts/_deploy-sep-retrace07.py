#!/usr/bin/env python3
"""Deploy Sep entry restore: retrace 0.7%, PAIR_TIME off, variant sep_retrace07."""
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]
REMOTE = "/opt/bilshenz/binance_trading_system/python"
PY = f"{REMOTE}/.venv/bin/python"

FILES = [
    "binance_trading_system/python/frozen_strategy.py",
    "binance_trading_system/python/momentum_scanner.py",
    "binance_trading_system/python/test_permanent_leak_locks.py",
]

CMD = rf"""
set -e
ENVF=/etc/bilshenz.env
# Force Sep knobs — clear Oct12 r5 trial env overrides
if grep -q '^SCANNER_RETRACE_PCT=' "$ENVF"; then
  sed -i 's/^SCANNER_RETRACE_PCT=.*/SCANNER_RETRACE_PCT=0.7/' "$ENVF"
else
  echo 'SCANNER_RETRACE_PCT=0.7' >> "$ENVF"
fi
if grep -q '^SCANNER_HEDGED_MAX_HOLD_MS=' "$ENVF"; then
  sed -i 's/^SCANNER_HEDGED_MAX_HOLD_MS=.*/SCANNER_HEDGED_MAX_HOLD_MS=0/' "$ENVF"
else
  echo 'SCANNER_HEDGED_MAX_HOLD_MS=0' >> "$ENVF"
fi
if grep -q '^SCANNER_GAIN_PCT=' "$ENVF"; then
  sed -i 's/^SCANNER_GAIN_PCT=.*/SCANNER_GAIN_PCT=5.0/' "$ENVF"
fi
grep -E 'SCANNER_RETRACE_PCT|SCANNER_HEDGED_MAX_HOLD_MS|SCANNER_GAIN_PCT' "$ENVF" || true

cd {REMOTE}
{PY} -m py_compile frozen_strategy.py momentum_scanner.py
{PY} - <<'PY'
from frozen_strategy import assert_frozen_contract, STRATEGY_VARIANT, RETRACE_ENTRY_PCT, HEDGED_MAX_HOLD_MS
import momentum_scanner as ms
s = assert_frozen_contract()
assert STRATEGY_VARIANT == "sep_retrace07"
assert abs(RETRACE_ENTRY_PCT - 0.7) < 1e-9
assert HEDGED_MAX_HOLD_MS == 0
assert abs(ms.RETRACE_ENTRY_PCT - 0.7) < 1e-9
assert ms.HEDGED_MAX_HOLD_MS == 0
print("CONTRACT_OK", STRATEGY_VARIANT, "retrace", RETRACE_ENTRY_PCT, "pair_hold_ms", HEDGED_MAX_HOLD_MS)
PY
{PY} test_permanent_leak_locks.py 2>&1 | tail -n 8
systemctl restart bilshenz-binance-api bilshenz-forward-bot
sleep 8
systemctl is-active bilshenz-binance-api bilshenz-forward-bot
{PY} - <<'PY'
import json, time, urllib.request, os
# re-import after restart via health/status
for i in range(20):
    h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=5).read())
    sc=h.get('scanner') or {{}}
    print(i, 'can', sc.get('can_execute'), 'tracked', sc.get('symbols_tracked'), 'part', sc.get('partition_usd'))
    if h.get('connected') and sc.get('symbols_tracked', 0) > 50:
        break
    time.sleep(1)
import importlib, sys
sys.path.insert(0, '{REMOTE}')
# live process knobs via a fresh import match disk; also print env
print('ENV_RETRACE', os.environ.get('SCANNER_RETRACE_PCT'))
# ask running service via a tiny marker in status if present
print('DISK', end=' ')
import frozen_strategy as fs, momentum_scanner as ms
print(fs.STRATEGY_VARIANT, ms.RETRACE_ENTRY_PCT, ms.HEDGED_MAX_HOLD_MS, ms.GAIN_THRESHOLD_PCT)
PY
# confirm running unit env
tr '\0' '\n' < /proc/$(systemctl show -p MainPID --value bilshenz-binance-api)/environ 2>/dev/null | grep -E 'SCANNER_RETRACE|SCANNER_HEDGED|SCANNER_GAIN' || echo 'proc_env_missing_scanner_knobs'
"""


def main() -> None:
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
    _, o, e = c.exec_command(CMD, timeout=180)
    print(o.read().decode("utf-8", "replace").encode("ascii", "replace").decode("ascii"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        print("STDERR", err.encode("ascii", "replace").decode("ascii")[-2500:])
    c.close()


if __name__ == "__main__":
    main()
