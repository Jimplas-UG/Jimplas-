#!/usr/bin/env bash
# Build release APK on VPS and publish to /opt/bilshenz/frontend/dist/
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/bilshenz}"
FRONTEND="$APP_DIR/frontend"
DIST="$FRONTEND/dist"
APK="$DIST/bilshenz-release.apk"
LOG="/var/log/bilshenz/apk-build.log"

mkdir -p "$DIST" /var/log/bilshenz
exec > >(tee -a "$LOG") 2>&1

echo "=== APK build on VPS $(date -Is) ==="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq openjdk-17-jdk-headless wget unzip curl

SDK="${ANDROID_HOME:-/opt/android-sdk}"
mkdir -p "$SDK/cmdline-tools"
if [[ ! -x "$SDK/cmdline-tools/latest/bin/sdkmanager" ]]; then
  echo "Installing Android SDK..."
  TMP=$(mktemp -d)
  cd "$TMP"
  wget -q https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip
  unzip -q commandlinetools-linux-11076708_latest.zip
  rm -rf "$SDK/cmdline-tools/latest"
  mkdir -p "$SDK/cmdline-tools/latest"
  mv cmdline-tools/* "$SDK/cmdline-tools/latest/"
  cd /
  rm -rf "$TMP"
fi

export ANDROID_HOME="$SDK"
export PATH="$SDK/cmdline-tools/latest/bin:$SDK/platform-tools:$PATH"
yes | sdkmanager --licenses >/dev/null || true
sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0"

cd "$APP_DIR"
git fetch origin && git reset --hard origin/main

cd "$FRONTEND"
npm ci 2>/dev/null || npm install

# Load desk key from server env if present
if [[ -f /etc/bilshenz.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source /etc/bilshenz.env
  set +a
fi

export EAS_BUILD=true
export BABEL_ENV=production
export EXPO_PUBLIC_DESK_LOCAL=0
export EXPO_PUBLIC_DESK_REMOTE=1
export EXPO_PUBLIC_DESK_API_URL="${EXPO_PUBLIC_DESK_API_URL:-http://157.245.33.42:8791}"
export EXPO_PUBLIC_BINANCE_API_URL="${EXPO_PUBLIC_BINANCE_API_URL:-${EXPO_PUBLIC_DESK_API_URL%/}/v1/binance}"

echo "desk url=$EXPO_PUBLIC_DESK_API_URL"
npx expo prebuild --platform android --clean

# Lower memory for 2GB VPS
if grep -q 'org.gradle.jvmargs' "$FRONTEND/android/gradle.properties"; then
  sed -i 's/org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx1536m -XX:MaxMetaspaceSize=384m/' "$FRONTEND/android/gradle.properties"
fi
echo "sdk.dir=$SDK" > "$FRONTEND/android/local.properties"

cd "$FRONTEND/android"
chmod +x gradlew
./gradlew assembleRelease --no-daemon

OUT=$(find app/build/outputs/apk/release -name '*.apk' | head -1)
cp "$OUT" "$APK"
chmod 644 "$APK"
ls -lh "$APK"

systemctl restart bilshenz-desk-api || true
sleep 2
curl -s http://127.0.0.1:8791/download
echo ""
echo "PHONE: http://$(curl -s ifconfig.me):8791/download/bilshenz.apk"
