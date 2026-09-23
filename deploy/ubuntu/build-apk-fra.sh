#!/usr/bin/env bash
# Build release APK on VPS from CURRENT /opt/bilshenz tree (no git reset).
# Injects Frankfurt EXPO_PUBLIC_* into the JS bundle.
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/bilshenz}"
FRONTEND="$APP_DIR/frontend"
DIST="$FRONTEND/dist"
LOG="/var/log/bilshenz/apk-build.log"
SDK="${ANDROID_HOME:-/opt/android-sdk}"
export DEBIAN_FRONTEND=noninteractive
export ANDROID_HOME="$SDK"
export PATH="$SDK/cmdline-tools/latest/bin:$SDK/platform-tools:$PATH"
# Inject public Expo env from host bilshenz.env (never hardcode secrets in git).
if [[ -f /etc/bilshenz.env ]]; then
  set -a
  # shellcheck disable=SC1091
  . /etc/bilshenz.env
  set +a
fi
export EXPO_PUBLIC_DESK_API_URL="${EXPO_PUBLIC_DESK_API_URL:-http://159.223.29.223:8791}"
export EXPO_PUBLIC_BINANCE_API_URL="${EXPO_PUBLIC_BINANCE_API_URL:-http://159.223.29.223:8766}"
export EXPO_PUBLIC_DESK_API_KEY="${EXPO_PUBLIC_DESK_API_KEY:-${DESK_API_KEY:-}}"
export EXPO_PUBLIC_BRIDGE_TOKEN="${EXPO_PUBLIC_BRIDGE_TOKEN:-${BRIDGE_TOKEN:-}}"
export EXPO_PUBLIC_DESK_REMOTE="1"
export EXPO_PUBLIC_BROKER_MODE="binance"
export EAS_BUILD="true"
export BABEL_ENV="production"
export NODE_ENV="production"

mkdir -p "$DIST" /var/log/bilshenz "$SDK"
exec >>"$LOG" 2>&1
echo ""
echo "=== FRA APK build $(date -Is) ==="

# Swap for 2GB
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

# Ensure Android SDK cmdline tools
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
# Low-RAM VPS: prefer reuse of existing android/ if present (resume after OOM).
if [[ ! -d "$FRONTEND/android" ]]; then
  rm -rf "$FRONTEND/.expo"
  npx expo prebuild --platform android --non-interactive
fi
cd "$FRONTEND/android"
chmod +x gradlew

# Harden gradle memory for ~2GB droplets (daemon death is usually OOM).
PROP=gradle.properties
touch "$PROP"
sed -i 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx1536m -XX:MaxMetaspaceSize=512m -XX:+HeapDumpOnOutOfMemoryError -Dfile.encoding=UTF-8/' "$PROP" 2>/dev/null || true
grep -q '^org.gradle.jvmargs=' "$PROP" || echo 'org.gradle.jvmargs=-Xmx1536m -XX:MaxMetaspaceSize=512m -XX:+HeapDumpOnOutOfMemoryError -Dfile.encoding=UTF-8' >> "$PROP"
sed -i 's/^org.gradle.workers.max=.*/org.gradle.workers.max=2/' "$PROP" 2>/dev/null || true
grep -q '^org.gradle.workers.max=' "$PROP" || echo 'org.gradle.workers.max=2' >> "$PROP"
sed -i 's/^org.gradle.parallel=.*/org.gradle.parallel=false/' "$PROP" 2>/dev/null || true
grep -q '^org.gradle.parallel=' "$PROP" || echo 'org.gradle.parallel=false' >> "$PROP"
sed -i 's/^org.gradle.daemon=.*/org.gradle.daemon=false/' "$PROP" 2>/dev/null || true
grep -q '^org.gradle.daemon=' "$PROP" || echo 'org.gradle.daemon=false' >> "$PROP"

export GRADLE_OPTS="-Xmx1536m -XX:MaxMetaspaceSize=512m -Dorg.gradle.daemon=false"
./gradlew assembleRelease --no-daemon --max-workers=2

APK_SRC=$(find app/build/outputs/apk/release -name "*.apk" | head -1)
test -n "$APK_SRC"
mkdir -p "$DIST"
cp -f "$APK_SRC" "$DIST/bilshenz-release.apk"
cp -f "$APK_SRC" "$DIST/bilshenz.apk"
sha256sum "$DIST/bilshenz-release.apk" | tee "$DIST/bilshenz-release.apk.sha256"
ls -lh "$DIST"/bilshenz*.apk
echo "APK_BUILD_OK $(date -Is)"
