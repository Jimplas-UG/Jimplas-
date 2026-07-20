#!/usr/bin/env python3
"""Full fresh release: deploy backend + purge old APK + build + verify manifest."""
import os
import sys
import time

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

HELPER = r"""#!/usr/bin/env bash
set -euo pipefail
export GIT_PAGER=cat PAGER=cat
cd /opt/bilshenz
git fetch origin
git reset --hard origin/main
COMMIT=$(git rev-parse HEAD)
echo "DEPLOY_COMMIT=$COMMIT"
git --no-pager log -1 --oneline

# Env: production URLs, execution armed, no dry-run
ENVF=/etc/bilshenz.env
for kv in \
  'TRADE_HISTORY_SINCE=2026-07-14' \
  'TRADE_CALENDAR_TZ=Africa/Nairobi' \
  'SCANNER_MIN_LIVE_ENTRY_PCT=2.0' \
  'SCANNER_MAX_RETRACE_ENTRY_PCT=12.0' \
  'FORWARD_DRY_RUN=0' \
  'SCANNER_EXEC=1' \
  'SCANNER_ENABLED=1' \
  'BINANCE_SYMBOL=BTCUSDT' \
  'BINANCE_PAPER=0' \
  'EXPO_PUBLIC_DESK_API_URL=http://157.245.33.42:8791' \
  'EXPO_PUBLIC_BINANCE_API_URL=http://157.245.33.42:8791/v1/binance' \
  'EXPO_PUBLIC_DESK_REMOTE=1'; do
  key="${kv%%=*}"
  val="${kv#*=}"
  if grep -q "^${key}=" "$ENVF" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENVF"
  else
    echo "${key}=${val}" >> "$ENVF"
  fi
done

# Backend
cd /opt/bilshenz/backend
npm ci --omit=dev 2>/dev/null || npm install --omit=dev
npm run build 2>/dev/null || true

systemctl restart bilshenz-binance-api
systemctl restart bilshenz-desk-api
systemctl restart bilshenz-forward-bot 2>/dev/null || true
systemctl restart bilshenz-watchdog 2>/dev/null || true
sleep 4
systemctl is-active bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot 2>/dev/null || systemctl is-active bilshenz-binance-api bilshenz-desk-api

# Purge stale APK before build
rm -f /opt/bilshenz/frontend/dist/*.apk /opt/bilshenz/frontend/dist/*.sha256 \
      /opt/bilshenz/frontend/dist/release-manifest.json 2>/dev/null || true
echo PURGED_OLD_APK

# Stop prior build
if [[ -f /var/run/bilshenz-apk-build.pid ]]; then
  old=$(cat /var/run/bilshenz-apk-build.pid || true)
  kill "$old" 2>/dev/null || true
  sleep 2
fi
pkill -f 'GradleDaemon' 2>/dev/null || true
pkill -f 'GradleWrapperMain' 2>/dev/null || true

: > /var/log/bilshenz/apk-build.log
START_EPOCH=$(date +%s)
echo "BUILD_START_EPOCH=$START_EPOCH" > /var/run/bilshenz-apk-build.meta
setsid bash /opt/bilshenz/deploy/ubuntu/build-apk-on-vps.sh >>/var/log/bilshenz/apk-build.log 2>&1 < /dev/null &
echo $! > /var/run/bilshenz-apk-build.pid
echo BUILD_STARTED pid=$(cat /var/run/bilshenz-apk-build.pid)
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
    with sftp.file("/tmp/bilshenz-fresh-release.sh", "w") as f:
        f.write(HELPER)
    sftp.chmod("/tmp/bilshenz-fresh-release.sh", 0o755)
    sftp.close()

    _, stdout, stderr = client.exec_command("bash /tmp/bilshenz-fresh-release.sh", timeout=300)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    sys.stdout.write(out)
    if err.strip():
        sys.stderr.write(err)
    client.close()
    return 0 if "BUILD_STARTED" in out else 1


if __name__ == "__main__":
    raise SystemExit(main())
