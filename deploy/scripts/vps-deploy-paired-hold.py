#!/usr/bin/env python3
"""Deploy paired-hold short_first fix to DO VPS and restart bridge."""
from __future__ import annotations

import os
import sys
from pathlib import Path

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
ROOT = Path(__file__).resolve().parents[2]
REMOTE_PY = "/opt/bilshenz/binance_trading_system/python"

FILES = [
    "momentum_scanner.py",
    "frozen_strategy.py",
    "strategy_guards.py",
    "leverage_policy.py",
    "test_scanner_15m.py",
    "test_frozen_strategy.py",
    "test_adopt_exchange.py",
]


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"connect {HOST} ...")
    c.connect(HOST, username="root", password=PASSWORD, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for name in FILES:
        local = ROOT / "binance_trading_system" / "python" / name
        if not local.is_file():
            print(f"SKIP missing {local}")
            continue
        remote = f"{REMOTE_PY}/{name}"
        print(f"upload {name} -> {remote}")
        sftp.put(str(local), remote)
    sftp.close()

    cmd = r"""
set -euo pipefail
ENVF=/etc/bilshenz.env
for kv in \
  'SCANNER_INVALIDATION_PCT=6.5' \
  'SCANNER_RESCUE_BUFFER_PCT=1.0' \
  'SCANNER_LONG_PULLBACK_PCT=0.5' \
  'SCANNER_SHORT_PULLBACK_PCT=1.5' \
  'SCANNER_SHORT_PULLBACK_MFE_PCT=1.5' \
  'SCANNER_SMART_EXIT_PCT=6.0' \
  'SCANNER_SHORT_PARTITION_PCT=50' \
  'SCANNER_LONG1_PARTITION_PCT=40' \
  'SCANNER_LONG2_PARTITION_PCT=40' \
  'SCANNER_EXEC=1' \
  'FORWARD_DRY_RUN=0'
do
  key="${kv%%=*}"
  val="${kv#*=}"
  if grep -q "^${key}=" "$ENVF" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENVF"
  else
    echo "${key}=${val}" >> "$ENVF"
  fi
done
echo '=== env knobs ==='
grep -E '^(SCANNER_INVALIDATION|SCANNER_RESCUE|SCANNER_LONG_PULLBACK|SCANNER_EXEC|FORWARD_DRY_RUN)=' "$ENVF"

cd /opt/bilshenz/binance_trading_system/python
echo '=== frozen contract ==='
python3 test_frozen_strategy.py
echo '=== scanner paired-hold tests ==='
python3 test_scanner_15m.py
echo '=== adopt regression ==='
python3 test_adopt_exchange.py

systemctl restart bilshenz-binance-api
sleep 7
systemctl is-active bilshenz-binance-api

set -a; . /etc/bilshenz.env; set +a
TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS --max-time 10 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json
curl -sS --max-time 10 -H "X-Bridge-Token: $TOKEN" 'http://127.0.0.1:8766/api/scanner/snapshot' > /tmp/snap.json || true
python3 <<'PY'
import json
h=json.load(open('/tmp/h.json'))
s=h.get('scanner') or {}
print('=== LIVE ===')
print('connected', h.get('connected'), 'mode', h.get('mode'))
print('can_execute', s.get('can_execute'), 'block', s.get('exec_block'))
print('active', s.get('active_symbol'), 'strategy', s.get('strategy_id') or s.get('frozen_strategy_id'))
# prove paired-hold markers loaded
import pathlib
src=pathlib.Path('/opt/bilshenz/binance_trading_system/python/momentum_scanner.py').read_text()
assert 'PAIR_INVALIDATION_PCT' in src
assert '_short_underwater' in src
assert '_hedge_rescue_ready' in src
assert 'paired hold' in src.lower() or 'PAIRED' in src or '_short_underwater' in src
print('paired_hold_markers OK')
import momentum_scanner as ms
print('live_invalidation', ms.PAIR_INVALIDATION_PCT, 'rescue_buf', ms.HEDGE_RESCUE_BUFFER_PCT)
PY
grep -E 'frozen strategy|PAIR_INVALIDATION|RESCUE|paired hold|INVALIDATION' /var/log/bilshenz/app.log 2>/dev/null | tail -n 20 || true
echo DEPLOY_OK
"""
    print("remote verify + restart ...")
    _, o, e = c.exec_command(cmd, timeout=240)
    out = o.read().decode("utf-8", errors="replace")
    err = e.read().decode("utf-8", errors="replace")
    sys.stdout.write(out)
    if err.strip():
        sys.stderr.write(err[-4000:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
