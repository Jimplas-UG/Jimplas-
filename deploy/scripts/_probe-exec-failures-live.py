#!/usr/bin/env python3
"""Read-only FRA: positions, health, recent execution failure lines."""
from pathlib import Path
import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
set -e
TOK=$(grep -E '^BRIDGE_TOKEN=' /etc/bilshenz.env | head -1 | cut -d= -f2- | tr -d '"'"'"')
echo ===HEALTH===
curl -sS http://127.0.0.1:8766/health | /opt/bilshenz/binance_trading_system/python/.venv/bin/python - <<'PY'
import sys, json
h=json.load(sys.stdin)
sc=h.get('scanner') or {}
print('mode', h.get('mode'), 'conn', h.get('connected'))
for k in ('can_execute','safe_mode','user_exec_halted','stuck_close_symbols','oversize_external_symbols','last_exec_error','partition_usd','rule_halt_codes','safe_mode_reason'):
    if k in sc or sc.get(k) is not None:
        print(k, sc.get(k))
print('keys', sorted([k for k in sc if any(x in k.lower() for x in ('safe','halt','stuck','over','err','can_'))]))
PY
echo ===POS===
curl -sS -H "Authorization: Bearer $TOK" http://127.0.0.1:8766/api/positions | /opt/bilshenz/binance_trading_system/python/.venv/bin/python - <<'PY'
import sys, json
d=json.load(sys.stdin)
for p in (d.get('positions') or []):
    vol=float(p.get('volume') or p.get('positionAmt') or 0)
    if abs(vol)>1e-12:
        print(p.get('symbol'), p.get('positionSide') or p.get('side'), vol, p.get('entryPrice') or p.get('price_open'), p.get('leverage'))
PY
echo ===LOG===
grep -E 'ack_missing|SAFE_MODE|OVERSIZE|long_residual|force_flat_4131|PARTIAL_CLOSE|SOLO_EXIT|INVALIDATION|PORTAL|-4005|-4131|CLOSE_PENDING|REFUSE_RESUME|emergency_halt|kernel_' /var/log/bilshenz/binance-api.log 2>/dev/null | tail -n 60 || true
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
        print("ERR", err.encode("ascii", "replace").decode("ascii")[-1500:])
    c.close()


if __name__ == "__main__":
    main()
