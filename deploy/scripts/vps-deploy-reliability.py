#!/usr/bin/env python3
"""Deploy reliability fixes (bridge + desk) and restart services."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

HELPER = r"""#!/usr/bin/env bash
set -euo pipefail
export GIT_PAGER=cat PAGER=cat
cd /opt/bilshenz
git fetch origin
git reset --hard origin/main
git --no-pager log -1 --oneline

# Ensure execution stays armed
ENVF=/etc/bilshenz.env
grep -q '^FORWARD_DRY_RUN=' "$ENVF" && sed -i 's/^FORWARD_DRY_RUN=.*/FORWARD_DRY_RUN=0/' "$ENVF" || echo 'FORWARD_DRY_RUN=0' >> "$ENVF"
grep -q '^SCANNER_EXEC=' "$ENVF" && sed -i 's/^SCANNER_EXEC=.*/SCANNER_EXEC=1/' "$ENVF" || echo 'SCANNER_EXEC=1' >> "$ENVF"
for kv in \
  'SCANNER_MIN_LIVE_ENTRY_PCT=2.0' \
  'SCANNER_MAX_RETRACE_ENTRY_PCT=12.0' \
  'SCANNER_LONG_PULLBACK_PCT=1.5' \
  'SCANNER_LONG_PULLBACK_MFE_PCT=1.5' \
  'SCANNER_SMART_EXIT_PCT=6.0' \
  'SCANNER_EXIT_COST_PCT=0.8' \
  'SCANNER_LONG1_PARTITION_PCT=12.5' \
  'SCANNER_LONG2_PARTITION_PCT=12.5' \
  'BINANCE_TESTNET=0' \
  'BINANCE_PAPER=0' \
  'FORWARD_DRY_RUN=0' \
  'SCANNER_EXEC=1'
do
  key="${kv%%=*}"
  val="${kv#*=}"
  if grep -q "^${key}=" "$ENVF" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENVF"
  else
    echo "${key}=${val}" >> "$ENVF"
  fi
done
# Hard cash-live assert
grep -q '^BINANCE_TESTNET=0$' "$ENVF" || { echo 'FATAL: BINANCE_TESTNET must be 0 for cash'; exit 1; }
grep -q '^FORWARD_DRY_RUN=0$' "$ENVF" || { echo 'FATAL: FORWARD_DRY_RUN must be 0 for cash'; exit 1; }

# Unlock stale 40/40 risk lock so balanced short sizing takes effect.
python3 - <<'PY'
import json, os
path = "/var/lib/bilshenz/scanner-risk.json"
try:
    raw = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh) or {}
    raw["long1_pct"] = 12.5
    raw["long2_pct"] = 12.5
    raw["short_pct"] = float(raw.get("short_pct") or 50)
    raw["locked"] = False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(raw, fh, indent=2)
    os.replace(tmp, path)
    print("risk_json_updated", raw)
except Exception as e:
    print("risk_json_skip", e)
PY

systemctl restart bilshenz-binance-api
systemctl restart bilshenz-desk-api
sleep 5
systemctl is-active bilshenz-binance-api bilshenz-desk-api

echo === health latency ===
/usr/bin/time -f 'elapsed=%e' curl -sS --max-time 10 -o /tmp/h.json -w 'code=%{http_code}\n' http://127.0.0.1:8766/health || true
python3 - <<'PY'
import json
h=json.load(open('/tmp/h.json'))
sc=h.get('scanner_stream') or {}
print('connected', h.get('connected'), 'scanner_ws', sc.get('ws_connected'), 'ticks', sc.get('ticks_received'), 'can_execute', (h.get('scanner') or {}).get('can_execute'))
PY

# Desk WS auth remapping: token query should not 403
set -a; . /etc/bilshenz.env; set +a
echo === desk health ===
curl -sS --max-time 5 http://127.0.0.1:8791/health; echo
"""


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    sftp = client.open_sftp()
    with sftp.file("/tmp/bilshenz-deploy-reliability.sh", "w") as f:
        f.write(HELPER)
    sftp.chmod("/tmp/bilshenz-deploy-reliability.sh", 0o755)
    sftp.close()
    _, stdout, stderr = client.exec_command("bash /tmp/bilshenz-deploy-reliability.sh", timeout=180)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    sys.stdout.write(out)
    if err.strip():
        sys.stderr.write(err)
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
