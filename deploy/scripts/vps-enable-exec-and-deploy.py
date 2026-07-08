#!/usr/bin/env python3
"""Enable scanner execution + deploy bridge/scanner fixes on VPS."""
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

# Arm live execution on linked Binance session (keep testnet unless already mainnet).
ENVF=/etc/bilshenz.env
touch "$ENVF"
grep -q '^FORWARD_DRY_RUN=' "$ENVF" && sed -i 's/^FORWARD_DRY_RUN=.*/FORWARD_DRY_RUN=0/' "$ENVF" || echo 'FORWARD_DRY_RUN=0' >> "$ENVF"
grep -q '^SCANNER_EXEC=' "$ENVF" && sed -i 's/^SCANNER_EXEC=.*/SCANNER_EXEC=1/' "$ENVF" || echo 'SCANNER_EXEC=1' >> "$ENVF"
grep -q '^SCANNER_ENABLED=' "$ENVF" && sed -i 's/^SCANNER_ENABLED=.*/SCANNER_ENABLED=1/' "$ENVF" || echo 'SCANNER_ENABLED=1' >> "$ENVF"

systemctl daemon-reload
systemctl restart bilshenz-binance-api
systemctl restart bilshenz-desk-api
sleep 4
systemctl is-active bilshenz-binance-api bilshenz-desk-api
echo '=== env ==='
grep -E '^(FORWARD_DRY_RUN|SCANNER_EXEC|SCANNER_ENABLED|BINANCE_TESTNET|BINANCE_PAPER)=' /etc/bilshenz.env
echo '=== health ==='
curl -sS --max-time 8 http://127.0.0.1:8766/health | head -c 700; echo
echo '=== scanner auth via desk ==='
set -a; . /etc/bilshenz.env; set +a
curl -sS --max-time 10 -H "Authorization: Bearer ${DESK_API_KEY}" http://127.0.0.1:8791/v1/binance/api/scanner/snapshot | head -c 500; echo
curl -sS --max-time 8 -H "Authorization: Bearer ${DESK_API_KEY}" http://127.0.0.1:8791/v1/binance/api/status | head -c 500; echo
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
    with sftp.file("/tmp/bilshenz-enable-exec.sh", "w") as f:
        f.write(HELPER)
    sftp.chmod("/tmp/bilshenz-enable-exec.sh", 0o755)
    sftp.close()
    _, stdout, stderr = client.exec_command("bash /tmp/bilshenz-enable-exec.sh", timeout=180)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    sys.stdout.write(out)
    if err.strip():
        sys.stderr.write(err)
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
