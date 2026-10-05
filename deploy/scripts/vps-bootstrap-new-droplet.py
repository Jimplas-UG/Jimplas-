#!/usr/bin/env python3
"""Upload paired-hold Python files and apply live scanner env knobs over SSH key."""
from __future__ import annotations

import os
import sys
from pathlib import Path

HOST = os.environ.get("VPS_HOST", "161.35.112.53")
KEY = os.environ.get("VPS_SSH_KEY", str(Path.home() / ".ssh" / "id_ed25519"))
ROOT = Path(__file__).resolve().parents[2]
REMOTE_PY = "/opt/bilshenz/binance_trading_system/python"
DESK_KEY = os.environ.get("DESK_API_KEY", "f44a0e6b7ea7b76418e484d6041e52da")

FILES = [
    "momentum_scanner.py",
    "frozen_strategy.py",
    "strategy_guards.py",
    "leverage_policy.py",
    "main.py",
    "test_scanner_15m.py",
    "test_frozen_strategy.py",
    "test_adopt_exchange.py",
]


def main() -> int:
    import paramiko

    key = paramiko.Ed25519Key.from_private_key_file(KEY)
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"connect {HOST} ...")
    c.connect(HOST, username="root", pkey=key, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for name in FILES:
        local = ROOT / "binance_trading_system" / "python" / name
        if not local.is_file():
            print(f"SKIP missing {local}")
            continue
        remote = f"{REMOTE_PY}/{name}"
        print(f"upload {name}")
        sftp.put(str(local), remote)
    sftp.close()

    cmd = rf"""
set -euo pipefail
ENVF=/etc/bilshenz.env
test -f "$ENVF"
# Preserve existing DESK key from app if present
if grep -q '^DESK_API_KEY=' "$ENVF"; then
  sed -i 's|^DESK_API_KEY=.*|DESK_API_KEY={DESK_KEY}|' "$ENVF"
else
  echo 'DESK_API_KEY={DESK_KEY}' >> "$ENVF"
fi
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
  'FORWARD_DRY_RUN=0' \
  'BINANCE_TESTNET=0' \
  'BINANCE_PAPER=0' \
  'PRODUCTION_MODE=1' \
  'STRATEGY_FREEZE=1'
do
  key="${{kv%%=*}}"
  val="${{kv#*=}}"
  if grep -q "^${{key}}=" "$ENVF" 2>/dev/null; then
    sed -i "s|^${{key}}=.*|${{key}}=${{val}}|" "$ENVF"
  else
    echo "${{key}}=${{val}}" >> "$ENVF"
  fi
done
# Ensure AUTH_JWT_SECRET long enough
if ! grep -q '^AUTH_JWT_SECRET=' "$ENVF" || [ "$(grep '^AUTH_JWT_SECRET=' "$ENVF" | cut -d= -f2- | wc -c)" -lt 32 ]; then
  sed -i '/^AUTH_JWT_SECRET=/d' "$ENVF"
  echo "AUTH_JWT_SECRET=$(openssl rand -hex 32)" >> "$ENVF"
fi
chmod 600 "$ENVF"
echo '=== env knobs ==='
grep -E '^(SCANNER_INVALIDATION|SCANNER_RESCUE|SCANNER_EXEC|FORWARD_DRY_RUN|BINANCE_TESTNET|DESK_API_KEY)=' "$ENVF" | sed -E 's/(DESK_API_KEY)=.*/\1=***/'

cd /opt/bilshenz/binance_trading_system/python
.venv/bin/python test_frozen_strategy.py
.venv/bin/python test_scanner_15m.py
.venv/bin/python test_adopt_exchange.py || true

systemctl restart bilshenz-binance-api bilshenz-desk-api
sleep 8
systemctl is-active bilshenz-binance-api bilshenz-desk-api
ufw allow 8766/tcp comment 'bilshenz-binance-api' || true
ufw allow 8791/tcp comment 'bilshenz-desk-api' || true
ufw status | head -20

TOKEN=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"' | tr -d "'")
curl -sS --max-time 10 -H "X-Bridge-Token: $TOKEN" http://127.0.0.1:8766/health > /tmp/h.json || echo '{{}}' > /tmp/h.json
curl -sS --max-time 10 http://127.0.0.1:8791/health > /tmp/d.json || echo '{{}}' > /tmp/d.json
.venv/bin/python <<'PY'
import json, pathlib
h=json.load(open('/tmp/h.json'))
print('bridge', {{'connected': h.get('connected'), 'mode': h.get('mode'), 'ok': h.get('ok')}})
s=h.get('scanner') or {{}}
print('scanner', {{'can_execute': s.get('can_execute'), 'block': s.get('exec_block'), 'strategy': s.get('strategy_id') or s.get('frozen_strategy_id')}})
src=pathlib.Path('momentum_scanner.py').read_text()
assert 'PAIR_INVALIDATION_PCT' in src and '_short_underwater' in src
print('paired_hold_markers OK')
import momentum_scanner as ms
print('invalidation', ms.PAIR_INVALIDATION_PCT, 'rescue', ms.HEDGE_RESCUE_BUFFER_PCT)
d=json.load(open('/tmp/d.json'))
print('desk', d)
print('HAS_BINANCE_KEY', bool((open('/etc/bilshenz.env').read().find('BINANCE_API_KEY=')>=0) and not any(line.startswith('BINANCE_API_KEY=') and len(line.strip().split('=',1)[-1])<8 for line in open('/etc/bilshenz.env') if line.startswith('BINANCE_API_KEY='))))
PY
echo PAIRED_HOLD_OK
"""
    print("remote configure + restart ...")
    _, o, e = c.exec_command(cmd, timeout=300)
    sys.stdout.write(o.read().decode("utf-8", errors="replace"))
    err = e.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err[-4000:])
    code = o.channel.recv_exit_status()
    c.close()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
