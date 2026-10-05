#!/usr/bin/env python3
"""Short FRA ops: exec check + start LF APK build (no long poll)."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

SCRIPT = r'''#!/usr/bin/env bash
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/bilshenz}"
FRONTEND="$APP_DIR/frontend"
DIST="$FRONTEND/dist"
LOG="/var/log/bilshenz/apk-build.log"
SDK="${ANDROID_HOME:-/opt/android-sdk}"
export DEBIAN_FRONTEND=noninteractive
export ANDROID_HOME="$SDK"
export PATH="$SDK/cmdline-tools/latest/bin:$SDK/platform-tools:$PATH"
export EXPO_PUBLIC_DESK_API_URL="http://159.223.29.223:8791"
export EXPO_PUBLIC_BINANCE_API_URL="http://159.223.29.223:8766"
export EXPO_PUBLIC_DESK_API_KEY="__DESK__"
export EXPO_PUBLIC_BRIDGE_TOKEN="__BRIDGE__"
export EXPO_PUBLIC_DESK_REMOTE="1"
export EXPO_PUBLIC_BROKER_MODE="binance"
export EAS_BUILD="true"
export BABEL_ENV="production"
export NODE_ENV="production"
mkdir -p "$DIST" /var/log/bilshenz "$SDK"
exec >>"$LOG" 2>&1
echo ""
echo "=== FRA APK build $(date -Is) ==="
if ! swapon --show | grep -q .; then
  if [[ ! -f /swapfile ]]; then
    fallocate -l 4G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=4096
    chmod 600 /swapfile
    mkswap /swapfile
  fi
  swapon /swapfile || true
fi
cd "$FRONTEND"
cat > .env <<EOF
EXPO_PUBLIC_DESK_API_URL=$EXPO_PUBLIC_DESK_API_URL
EXPO_PUBLIC_BINANCE_API_URL=$EXPO_PUBLIC_BINANCE_API_URL
EXPO_PUBLIC_DESK_API_KEY=$EXPO_PUBLIC_DESK_API_KEY
EXPO_PUBLIC_BRIDGE_TOKEN=$EXPO_PUBLIC_BRIDGE_TOKEN
EXPO_PUBLIC_DESK_REMOTE=1
EXPO_PUBLIC_BROKER_MODE=binance
EOF
npm ci 2>/dev/null || npm install
export JAVA_HOME=$(dirname $(dirname $(readlink -f $(which javac))))
rm -rf android .expo
npx expo prebuild --platform android --non-interactive
cd android
chmod +x gradlew
./gradlew assembleRelease --no-daemon
APK_SRC=$(find app/build/outputs/apk/release -name "*.apk" | head -1)
test -n "$APK_SRC"
mkdir -p "$DIST"
cp -f "$APK_SRC" "$DIST/bilshenz-release.apk"
cp -f "$APK_SRC" "$DIST/bilshenz.apk"
sha256sum "$DIST/bilshenz-release.apk" | tee "$DIST/bilshenz-release.apk.sha256"
ls -lh "$DIST"/bilshenz*.apk
echo "APK_BUILD_OK $(date -Is)"
'''


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=30, look_for_keys=False, allow_agent=False)

    # sync critical py + frontend ws
    sftp = c.open_sftp()
    for name in ("main.py", "binance_connector.py"):
        sftp.put(str(ROOT / "binance_trading_system/python" / name), f"/opt/bilshenz/binance_trading_system/python/{name}")
    for rel in (
        "frontend/lib/wsReconnect.js",
        "frontend/broker/binanceTickStream.js",
        "frontend/broker/binanceScannerApi.js",
        "frontend/hooks/useTickScanner.js",
        "frontend/app.json",
    ):
        local = ROOT / rel
        if local.exists():
            sftp.put(str(local), f"/opt/bilshenz/{rel}")
    sftp.close()
    print("uploaded")

    _, o, e = c.exec_command(
        r"""
python3 - <<'PY'
from pathlib import Path
d={}
for l in Path('/etc/bilshenz.env').read_text().splitlines():
    if '=' in l and not l.startswith('#'):
        k,v=l.split('=',1); d[k]=v.strip().strip('"').strip("'")
print(d.get('BRIDGE_TOKEN',''))
print(d.get('DESK_API_KEY',''))
PY
""",
        timeout=20,
    )
    tlines = o.read().decode().splitlines()
    bridge, desk = (tlines + ["", ""])[:2]
    script = SCRIPT.replace("__BRIDGE__", bridge).replace("__DESK__", desk)
    data = script.encode("utf-8")  # LF only from python \n

    sftp = c.open_sftp()
    with sftp.file("/opt/bilshenz/deploy/ubuntu/build-apk-fra.sh", "wb") as f:
        f.write(data)
    sftp.close()

    _, o, e = c.exec_command(
        r"""
set -e
python3 -c "from pathlib import Path; b=Path('/opt/bilshenz/deploy/ubuntu/build-apk-fra.sh').read_bytes(); assert b'\r' not in b; print('lf_ok', len(b))"
chmod +x /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh
bash -n /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh
systemctl restart bilshenz-binance-api
sleep 6
python3 - <<'PY'
import json, urllib.request
from pathlib import Path
tok=''
for l in Path('/etc/bilshenz.env').read_text().splitlines():
  if l.startswith('BRIDGE_TOKEN='):
    tok=l.split('=',1)[1].strip().strip('"').strip("'")
req=urllib.request.Request('http://127.0.0.1:8766/api/scanner/exec', data=b'{"enabled":true}', headers={'X-Bridge-Token':tok,'Content-Type':'application/json'}, method='POST')
print(json.loads(urllib.request.urlopen(req, timeout=10).read().decode()))
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read().decode())
s=h.get('scanner') or {}
print('connected', h.get('connected'), 'exec', s.get('can_execute'), 'block', s.get('exec_block'), 'active', s.get('active_symbol'), 'cool', h.get('rest_cool_s'))
st=json.loads(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8766/api/status', headers={'X-Bridge-Token':tok}), timeout=8).read().decode())
print('status_connected', st.get('connected'), 'trade_allowed', st.get('trade_allowed'))
PY
systemctl restart bilshenz-forward-bot
sleep 3
systemctl is-active bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot
pkill -f build-apk-fra.sh || true
rm -f /var/log/bilshenz/apk-build.log /var/log/bilshenz/apk-build-nohup.out
nohup bash /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh >/var/log/bilshenz/apk-build-nohup.out 2>&1 &
echo BUILD_STARTED
sleep 8
ps -ef | grep -E 'build-apk-fra|gradlew|expo' | grep -v grep | head || echo waiting
tail -n 15 /var/log/bilshenz/apk-build.log || cat /var/log/bilshenz/apk-build-nohup.out || true
""",
        timeout=90,
    )
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
