#!/usr/bin/env python3
import json
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

CMD = r"""
set -a; . /etc/bilshenz.env; set +a
echo === RISK_JSON ===
python3 - <<'PY'
import json
print(json.dumps(json.load(open('/var/lib/bilshenz/scanner-risk.json')), indent=2))
PY
echo === ENV_KEYS ===
grep -E 'SCANNER_(GAIN|RETRACE|LONG1_PCT|LONG2_PCT|LONG_PULLBACK|SMART_EXIT|SHORT_PARTITION|LONG1_PARTITION|LONG2_PARTITION|ONE_TRADE|EXEC|ENTRY_TF)|FORWARD_DRY_RUN|BINANCE_PAPER|BINANCE_TESTNET' /etc/bilshenz.env | sort
echo === HEALTH ===
curl -sS --max-time 8 http://127.0.0.1:8766/health > /tmp/h.json
python3 - <<'PY'
import json
h = json.load(open('/tmp/h.json'))
s = h.get('scanner') or {}
keys = [
  'can_execute','exec_enabled','exec_block','short_partition_pct','long1_partition_pct',
  'long2_partition_pct','partition_usd','active_symbol','one_trade'
]
print(json.dumps({k: s.get(k) for k in keys}, indent=2))
print('mode', h.get('mode'), 'connected', h.get('connected'))
print('scanner_keys', sorted(s.keys())[:40])
PY
echo === POSITIONS ===
curl -sS --max-time 8 http://127.0.0.1:8766/api/positions | python3 -m json.tool 2>/dev/null | head -n 100
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=25, look_for_keys=False, allow_agent=False)
    _, stdout, stderr = client.exec_command(CMD, timeout=60)
    sys.stdout.write(stdout.read().decode("utf-8", errors="replace"))
    err = stderr.read().decode("utf-8", errors="replace")
    if err.strip():
        sys.stderr.write(err)
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
