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
sdkmanager "platform-tools" "platforms;android-34" "platforms;android-35" "build-tools;34.0.0" "build-tools;35.0.0" || \
  sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0"

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

# Enforce compileSdk 35 via gradle.properties (Expo reads android.compileSdkVersion from here)
PROP="$FRONTEND/android/gradle.properties"
touch "$PROP"
if grep -q '^android.compileSdkVersion=' "$PROP"; then
  sed -i 's/^android.compileSdkVersion=.*/android.compileSdkVersion=35/' "$PROP"
else
  echo 'android.compileSdkVersion=35' >> "$PROP"
fi
if grep -q '^android.targetSdkVersion=' "$PROP"; then
  sed -i 's/^android.targetSdkVersion=.*/android.targetSdkVersion=34/' "$PROP"
else
  echo 'android.targetSdkVersion=34' >> "$PROP"
fi
# Ensure splash drawable exists (expo-splash-screen expects splashscreen_logo)
RES_DIR="$FRONTEND/android/app/src/main/res/drawable"
mkdir -p "$RES_DIR"
if [[ ! -f "$RES_DIR/splashscreen_logo.png" ]]; then
  if [[ -f "$FRONTEND/assets/splash-icon.png" ]]; then
    cp -f "$FRONTEND/assets/splash-icon.png" "$RES_DIR/splashscreen_logo.png"
  elif [[ -f "$FRONTEND/assets/icon.png" ]]; then
    cp -f "$FRONTEND/assets/icon.png" "$RES_DIR/splashscreen_logo.png"
  fi
fi
grep -nE 'compileSdk|android.compileSdkVersion' "$FRONTEND/android/build.gradle" "$PROP" 2>/dev/null || true
ls -la "$RES_DIR/splashscreen_logo.png" 2>/dev/null || echo "WARN: no splashscreen_logo.png"

# 2GB RAM + 4GB swap: enough heap/metaspace for release; skip lint to save memory
sed -i 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx1536m -XX:MaxMetaspaceSize=512m -XX:+HeapDumpOnOutOfMemoryError/' "$PROP" || true
if ! grep -q '^org.gradle.jvmargs=' "$PROP"; then
  echo 'org.gradle.jvmargs=-Xmx1536m -XX:MaxMetaspaceSize=512m -XX:+HeapDumpOnOutOfMemoryError' >> "$PROP"
fi
if ! grep -q '^android.enableLint=' "$PROP"; then
  echo 'android.enableLint=false' >> "$PROP"
fi
if ! grep -q 'reactNativeArchitectures' "$PROP"; then
  echo 'reactNativeArchitectures=armeabi-v7a,arm64-v8a' >> "$PROP"
else
  sed -i 's/^reactNativeArchitectures=.*/reactNativeArchitectures=armeabi-v7a,arm64-v8a/' "$PROP"
fi
echo "sdk.dir=$SDK" > "$FRONTEND/android/local.properties"

cd "$FRONTEND/android"
chmod +x gradlew
# Double-check effective compileSdk before assemble
./gradlew -q printCompileSdk 2>/dev/null || \
  ./gradlew -q properties 2>/dev/null | grep -E 'compileSdk|android.compileSdkVersion' || true
grep -nE 'android\.compileSdkVersion|compileSdkVersion' gradle.properties build.gradle app/build.gradle || true
./gradlew assembleRelease --no-daemon --stacktrace \
  -PreactNativeArchitectures=armeabi-v7a,arm64-v8a \
  -x lint -x lintVitalRelease -x lintVitalAnalyzeRelease

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
