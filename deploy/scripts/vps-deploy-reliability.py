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
for kv in 'SCANNER_MIN_LIVE_ENTRY_PCT=2.0' 'SCANNER_MAX_RETRACE_ENTRY_PCT=12.0'; do
  key="${kv%%=*}"
  val="${kv#*=}"
  if grep -q "^${key}=" "$ENVF" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENVF"
  else
    echo "${key}=${val}" >> "$ENVF"
  fi
done

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
