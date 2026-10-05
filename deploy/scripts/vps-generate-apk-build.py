#!/usr/bin/env python3
"""Generate LF-only APK build script on FRA, start build, wait for cool-down exec."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

# Entire build script written on Linux — no Windows CRLF possible.
BUILD_SCRIPT = r'''#!/usr/bin/env bash
# Build release APK on VPS from CURRENT /opt/bilshenz tree (no git reset).
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

if [[ ! -x "$SDK/cmdline-tools/latest/bin/sdkmanager" ]]; then
  apt-get update -qq
  apt-get install -y -qq openjdk-17-jdk-headless wget unzip curl
  TMP=$(mktemp -d)
  cd "$TMP"
  wget -q https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip -O cmdtools.zip
  unzip -q cmdtools.zip
  mkdir -p "$SDK/cmdline-tools/latest"
  mv cmdline-tools/* "$SDK/cmdline-tools/latest/" || true
  yes | sdkmanager --licenses >/dev/null || true
  sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0" || true
  cd "$FRONTEND"
fi

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
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    c.get_transport().set_keepalive(20)

    # Upload connector+main for status/exec fixes
    sftp = c.open_sftp()
    root = Path(__file__).resolve().parents[2]
    for name in ("main.py", "binance_connector.py"):
        sftp.put(
            str(root / "binance_trading_system" / "python" / name),
            f"/opt/bilshenz/binance_trading_system/python/{name}",
        )
    sftp.close()

    # Write build script via SFTP as binary LF
    # First fetch tokens
    _, o, _ = c.exec_command(
        "python3 -c \"from pathlib import Path\n"
        "d={}\n"
        "for l in Path('/etc/bilshenz.env').read_text().splitlines():\n"
        "  if '=' in l and not l.startswith('#'):\n"
        "    k,v=l.split('=',1); d[k]=v.strip().strip(chr(34)).strip(chr(39))\n"
        "print(d.get('BRIDGE_TOKEN','')); print(d.get('DESK_API_KEY',''))\"",
        timeout=20,
    )
    lines = o.read().decode().splitlines()
    bridge = lines[0].strip() if lines else ""
    desk = lines[1].strip() if len(lines) > 1 else ""
    script = BUILD_SCRIPT.replace("__BRIDGE__", bridge).replace("__DESK__", desk)
    script_bytes = script.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")

    sftp = c.open_sftp()
    with sftp.file("/opt/bilshenz/deploy/ubuntu/build-apk-fra.sh", "wb") as f:
        f.write(script_bytes)
    sftp.close()

    start = r"""
set -e
python3 - <<'PY'
from pathlib import Path
b=Path('/opt/bilshenz/deploy/ubuntu/build-apk-fra.sh').read_bytes()
assert b'\r' not in b, 'CRLF still present'
print('script_ok_bytes', len(b), 'cr', b.count(b'\r'))
print(b.splitlines()[3])
PY
chmod +x /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh
bash -n /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh && echo bash_syntax_ok

# upload frontend ws files already done; bump version if needed
python3 - <<'PY'
import json
from pathlib import Path
p=Path('/opt/bilshenz/frontend/app.json')
j=json.loads(p.read_text())
print('version', j['expo'].get('version'), 'code', j['expo']['android'].get('versionCode'))
PY

# restart bridge with keys
systemctl restart bilshenz-binance-api
sleep 8
systemctl restart bilshenz-forward-bot || true

# enable exec
python3 - <<'PY'
import json, urllib.request
from pathlib import Path
tok=''
for l in Path('/etc/bilshenz.env').read_text().splitlines():
    if l.startswith('BRIDGE_TOKEN='):
        tok=l.split('=',1)[1].strip().strip('"').strip("'")
req=urllib.request.Request(
  'http://127.0.0.1:8766/api/scanner/exec',
  data=json.dumps({'enabled': True}).encode(),
  headers={'X-Bridge-Token': tok, 'Content-Type': 'application/json'},
  method='POST',
)
try:
  with urllib.request.urlopen(req, timeout=10) as r:
    print('exec', json.loads(r.read().decode()))
except Exception as e:
  print('exec_err', e)
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=10).read().decode())
s=h.get('scanner') or {}
print('health', h.get('connected'), h.get('mode'), 'cool', h.get('rest_cool_s'), 'exec', s.get('can_execute'), 'block', s.get('exec_block'), 'active', s.get('active_symbol'))
PY

pkill -f build-apk-fra.sh || true
pkill -f 'gradlew assembleRelease' || true
rm -f /var/log/bilshenz/apk-build.log /var/log/bilshenz/apk-build-nohup.out
nohup bash /opt/bilshenz/deploy/ubuntu/build-apk-fra.sh >/var/log/bilshenz/apk-build-nohup.out 2>&1 &
echo BUILD_PID=$!
sleep 10
ps -ef | grep -E 'build-apk-fra|gradlew|expo|npm' | grep -v grep | head -n 15 || true
echo '---nohup---'
cat /var/log/bilshenz/apk-build-nohup.out || true
echo '---log---'
tail -n 40 /var/log/bilshenz/apk-build.log || true
"""
    _, o, e = c.exec_command(start, timeout=120)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-2000:])

    # poll build up to ~25 min
    for i in range(50):
        time.sleep(30)
        _, o, _ = c.exec_command(
            r"""
ps -ef | grep -E 'build-apk-fra|gradlew|expo prebuild' | grep -v grep | head -n 3 || echo no_proc
tail -n 5 /var/log/bilshenz/apk-build.log 2>/dev/null || true
grep -E 'APK_BUILD_OK|BUILD FAILED|FATAL|Error:' /var/log/bilshenz/apk-build.log 2>/dev/null | tail -n 5 || true
ls -lh /opt/bilshenz/frontend/dist/bilshenz.apk 2>/dev/null | awk '{print $5,$6,$7,$8,$9}'
""",
            timeout=30,
        )
        out = o.read().decode("utf-8", "replace")
        print(f"--- poll {i} ---")
        print(out)
        if "APK_BUILD_OK" in out:
            _, o2, _ = c.exec_command(
                r"""
python3 - <<'PY'
import json, hashlib, time
from pathlib import Path
apk=Path('/opt/bilshenz/frontend/dist/bilshenz.apk')
j=json.loads(Path('/opt/bilshenz/frontend/app.json').read_text())
sha=hashlib.sha256(apk.read_bytes()).hexdigest()
manifest={
  'versionName': j['expo'].get('version'),
  'versionCode': j['expo'].get('android',{}).get('versionCode'),
  'apkPresent': True,
  'size': apk.stat().st_size,
  'sha256': sha,
  'builtAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(apk.stat().st_mtime)),
  'url': 'http://159.223.29.223:8791/download/bilshenz.apk',
}
Path('/opt/bilshenz/frontend/dist/release-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
print(json.dumps(manifest, indent=2))
PY
curl -sS -m 8 -I http://127.0.0.1:8791/download/bilshenz.apk | head -n 10
# final exec check
python3 - <<'PY'
import json, urllib.request
from pathlib import Path
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read().decode())
s=h.get('scanner') or {}
print('FINAL connected', h.get('connected'), 'exec', s.get('can_execute'), 'block', s.get('exec_block'), 'active', s.get('active_symbol'), 'cool', h.get('rest_cool_s'))
PY
systemctl is-active bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot
""",
                timeout=60,
            )
            print(o2.read().decode("utf-8", "replace"))
            c.close()
            return 0
        if "no_proc" in out and i > 2 and "APK_BUILD_OK" not in out:
            # check for failure
            if "BUILD FAILED" in out or "Error:" in out:
                c.close()
                return 1
    c.close()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
