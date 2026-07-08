#!/usr/bin/env bash
# Build release APK on VPS (2GB RAM safe) and publish download.
# Run: bash /opt/bilshenz/deploy/ubuntu/build-apk-on-vps.sh
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/bilshenz}"
FRONTEND="$APP_DIR/frontend"
DIST="$FRONTEND/dist"
APK="$DIST/bilshenz-release.apk"
LOG="/var/log/bilshenz/apk-build.log"
SDK="${ANDROID_HOME:-/opt/android-sdk}"
export DEBIAN_FRONTEND=noninteractive
export ANDROID_HOME="$SDK"
export PATH="$SDK/cmdline-tools/latest/bin:$SDK/platform-tools:$PATH"

mkdir -p "$DIST" /var/log/bilshenz "$SDK"
exec >>"$LOG" 2>&1
echo ""
echo "=== APK build on VPS $(date -Is) ==="

# Swap for 2GB droplet Gradle builds
if ! swapon --show | grep -q .; then
  if [[ ! -f /swapfile ]]; then
    fallocate -l 4G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=4096
    chmod 600 /swapfile
    mkswap /swapfile
  fi
  swapon /swapfile || true
fi

apt-get update -qq
apt-get install -y -qq openjdk-17-jdk-headless wget unzip curl ca-certificates

if [[ ! -x "$SDK/cmdline-tools/latest/bin/sdkmanager" ]]; then
  echo "Installing Android cmdline-tools..."
  TMP=$(mktemp -d)
  cd "$TMP"
  wget -q https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
  unzip -q commandlinetools-linux-11076708_latest.zip
  rm -rf "$SDK/cmdline-tools/latest"
  mkdir -p "$SDK/cmdline-tools/latest"
  mv cmdline-tools/* "$SDK/cmdline-tools/latest/"
  rm -rf "$TMP"
fi

yes | sdkmanager --licenses >/dev/null || true
sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0"

cd "$APP_DIR"
git fetch origin
git reset --hard origin/main

cd "$FRONTEND"
npm ci 2>/dev/null || npm install --legacy-peer-deps

if [[ -f /etc/bilshenz.env ]]; then
  set -a
  # shellcheck disable=SC1091
  . /etc/bilshenz.env
  set +a
fi

export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}"
export PATH="$JAVA_HOME/bin:$PATH"
export EAS_BUILD=true
export BABEL_ENV=production
export NODE_ENV=production
export EXPO_PUBLIC_DESK_LOCAL=0
export EXPO_PUBLIC_DESK_REMOTE=1
export EXPO_PUBLIC_DESK_API_URL="${EXPO_PUBLIC_DESK_API_URL:-http://157.245.33.42:8791}"
export EXPO_PUBLIC_BINANCE_API_URL="${EXPO_PUBLIC_BINANCE_API_URL:-${EXPO_PUBLIC_DESK_API_URL%/}/v1/binance}"
if [[ -n "${DESK_API_KEY:-}" ]]; then
  export EXPO_PUBLIC_DESK_API_KEY="$DESK_API_KEY"
fi

echo "desk=$EXPO_PUBLIC_DESK_API_URL binance=$EXPO_PUBLIC_BINANCE_API_URL hasKey=${EXPO_PUBLIC_DESK_API_KEY:+yes}"
npx expo prebuild --platform android --clean

# 2GB RAM: keep Gradle lean + phone ABI only
sed -i 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx1024m -XX:MaxMetaspaceSize=256m -XX:+HeapDumpOnOutOfMemoryError/' "$FRONTEND/android/gradle.properties" || true
if ! grep -q 'reactNativeArchitectures' "$FRONTEND/android/gradle.properties"; then
  echo 'reactNativeArchitectures=armeabi-v7a,arm64-v8a' >> "$FRONTEND/android/gradle.properties"
else
  sed -i 's/^reactNativeArchitectures=.*/reactNativeArchitectures=armeabi-v7a,arm64-v8a/' "$FRONTEND/android/gradle.properties"
fi
echo "sdk.dir=$SDK" > "$FRONTEND/android/local.properties"

cd "$FRONTEND/android"
chmod +x gradlew
./gradlew assembleRelease --no-daemon --stacktrace -PreactNativeArchitectures=armeabi-v7a,arm64-v8a

OUT=$(find app/build/outputs/apk/release -name '*.apk' | head -1)
test -n "$OUT"
cp -f "$OUT" "$APK"
chmod 644 "$APK"
ls -lh "$APK"
sha256sum "$APK" | tee "$DIST/bilshenz-release.sha256"

systemctl restart bilshenz-desk-api || true
sleep 2
curl -s http://127.0.0.1:8791/download || true
echo ""
PUB=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
echo "PHONE http://${PUB}:8791/download/bilshenz.apk"
echo "=== DONE $(date -Is) ==="
