#!/usr/bin/env bash
# Build release APK on VPS from latest origin/main — NO reuse of old artifacts.
# Run: bash /opt/bilshenz/deploy/ubuntu/build-apk-on-vps.sh
set -euo pipefail
APP_DIR="${APP_DIR:-/opt/bilshenz}"
FRONTEND="$APP_DIR/frontend"
DIST="$FRONTEND/dist"
LOG="/var/log/bilshenz/apk-build.log"
SDK="${ANDROID_HOME:-/opt/android-sdk}"
BUILD_STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

export DEBIAN_FRONTEND=noninteractive
export ANDROID_HOME="$SDK"
export PATH="$SDK/cmdline-tools/latest/bin:$SDK/platform-tools:$PATH"

mkdir -p "$DIST" /var/log/bilshenz "$SDK"
exec >>"$LOG" 2>&1
echo ""
echo "=== FRESH APK build START $BUILD_STAMP ==="

# ── 1. Latest source ──────────────────────────────────────────────────────
cd "$APP_DIR"
git fetch origin
git reset --hard origin/main
GIT_COMMIT="$(git rev-parse HEAD)"
GIT_SHORT="$(git rev-parse --short HEAD)"
echo "GIT_COMMIT=$GIT_COMMIT"

# Read version from app.json
VERSION_NAME="$(python3 - <<'PY'
import json
from pathlib import Path
j=json.loads(Path("frontend/app.json").read_text())
print(j.get("expo",{}).get("version","0.0.0"))
PY
)"
VERSION_CODE="$(python3 - <<'PY'
import re
from pathlib import Path
t = Path("frontend/app.config.js").read_text()
m = re.search(r"versionCode:\s*(\d+)", t)
print(m.group(1) if m else "120")
PY
)"
APK_NAME="bilshenz-v${VERSION_NAME}-b${VERSION_CODE}-${GIT_SHORT}.apk"
APK="$DIST/$APK_NAME"
MANIFEST="$DIST/release-manifest.json"

echo "VERSION_NAME=$VERSION_NAME VERSION_CODE=$VERSION_CODE APK_NAME=$APK_NAME"

# ── 2. PURGE all old build artifacts (release-blocking: never reuse) ───────
echo "Purging old APK and build caches..."
rm -f "$DIST"/*.apk "$DIST"/*.sha256 "$DIST"/release-manifest.json 2>/dev/null || true
rm -rf "$FRONTEND/android" \
       "$FRONTEND/.expo" \
       "$FRONTEND/node_modules/.cache" \
       "$HOME/.gradle/caches/transforms-"* 2>/dev/null || true

# ── 3. Swap for 2GB droplet ───────────────────────────────────────────────
if ! swapon --show | grep -q .; then
  if [[ ! -f /swapfile ]]; then
    fallocate -l 4G /swapfile || dd if=/dev/zero of=/swapfile bs=1M count=4096
    chmod 600 /swapfile
    mkswap /swapfile
  fi
  swapon /swapfile || true
fi

apt-get update -qq
apt-get install -y -qq openjdk-17-jdk-headless wget unzip curl ca-certificates python3

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
sdkmanager "platform-tools" "platforms;android-35" "build-tools;35.0.0" || \
  sdkmanager "platform-tools" "platforms;android-34" "build-tools;34.0.0"

cd "$FRONTEND"
rm -rf node_modules
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
export NODE_OPTIONS="--max-old-space-size=2048"
export EXPO_NO_METRO_CACHE=1
export EXPO_PUBLIC_DESK_LOCAL=0
export EXPO_PUBLIC_DESK_REMOTE=1
export EXPO_PUBLIC_DESK_API_URL="${EXPO_PUBLIC_DESK_API_URL:-http://157.245.33.42:8791}"
export EXPO_PUBLIC_BINANCE_API_URL="${EXPO_PUBLIC_BINANCE_API_URL:-${EXPO_PUBLIC_DESK_API_URL%/}/v1/binance}"
if [[ -n "${DESK_API_KEY:-}" ]]; then
  export EXPO_PUBLIC_DESK_API_KEY="$DESK_API_KEY"
fi

echo "desk=$EXPO_PUBLIC_DESK_API_URL binance=$EXPO_PUBLIC_BINANCE_API_URL commit=$GIT_SHORT"

npx expo prebuild --platform android --clean

# ── 4. Fix splashscreen_logo in ALL drawable buckets (Gradle AAPT fix) ────
SPLASH_SRC=""
for f in "$FRONTEND/assets/splash-icon.png" "$FRONTEND/assets/icon.png"; do
  [[ -f "$f" ]] && SPLASH_SRC="$f" && break
done
if [[ -n "$SPLASH_SRC" ]]; then
  RES_BASE="$FRONTEND/android/app/src/main/res"
  for d in drawable drawable-mdpi drawable-hdpi drawable-xhdpi drawable-xxhdpi drawable-xxxhdpi; do
    mkdir -p "$RES_BASE/$d"
    cp -f "$SPLASH_SRC" "$RES_BASE/$d/splashscreen_logo.png"
  done
  echo "splashscreen_logo installed from $SPLASH_SRC"
fi

PROP="$FRONTEND/android/gradle.properties"
touch "$PROP"
grep -q '^android.compileSdkVersion=' "$PROP" && sed -i 's/^android.compileSdkVersion=.*/android.compileSdkVersion=35/' "$PROP" || echo 'android.compileSdkVersion=35' >> "$PROP"
grep -q '^android.targetSdkVersion=' "$PROP" && sed -i 's/^android.targetSdkVersion=.*/android.targetSdkVersion=34/' "$PROP" || echo 'android.targetSdkVersion=34' >> "$PROP"
sed -i 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx2048m -XX:MaxMetaspaceSize=768m -XX:+HeapDumpOnOutOfMemoryError/' "$PROP" 2>/dev/null || true
grep -q '^org.gradle.jvmargs=' "$PROP" || echo 'org.gradle.jvmargs=-Xmx2048m -XX:MaxMetaspaceSize=768m -XX:+HeapDumpOnOutOfMemoryError' >> "$PROP"
grep -q '^android.enableLint=' "$PROP" || echo 'android.enableLint=false' >> "$PROP"
grep -q '^org.gradle.parallel=' "$PROP" || echo 'org.gradle.parallel=false' >> "$PROP"
grep -q '^org.gradle.workers.max=' "$PROP" || echo 'org.gradle.workers.max=2' >> "$PROP"
sed -i 's/^reactNativeArchitectures=.*/reactNativeArchitectures=arm64-v8a/' "$PROP" 2>/dev/null || echo 'reactNativeArchitectures=arm64-v8a' >> "$PROP"
echo "sdk.dir=$SDK" > "$FRONTEND/android/local.properties"

# Disable lint in app/build.gradle
APP_GRADLE="$FRONTEND/android/app/build.gradle"
if [[ -f "$APP_GRADLE" ]] && ! grep -q 'checkReleaseBuilds false' "$APP_GRADLE"; then
  sed -i '/android {/a\    lint { checkReleaseBuilds false; abortOnError false }' "$APP_GRADLE" || true
fi

# ── 5. JS bundle preflight (fail fast with readable error) ─────────────────
cd "$FRONTEND"
echo "JS bundle preflight..."
npx react-native bundle \
  --platform android \
  --dev false \
  --entry-file index.js \
  --bundle-output /tmp/bilshenz-preflight.bundle \
  --assets-dest /tmp/bilshenz-preflight-assets \
  2>&1 | tail -n 30
echo "Preflight bundle OK"

# ── 6. Gradle release (single ABI, no lint) ───────────────────────────────
cd "$FRONTEND/android"
chmod +x gradlew
./gradlew clean --no-daemon
./gradlew assembleRelease --no-daemon --stacktrace \
  -PreactNativeArchitectures=arm64-v8a \
  -x lint -x lintVitalRelease -x lintVitalAnalyzeRelease \
  -x lintAnalyzeRelease -x lintReportRelease

OUT=$(find app/build/outputs/apk/release -name '*.apk' 2>/dev/null | head -1)
if [[ -z "$OUT" || ! -f "$OUT" ]]; then
  echo "FATAL: Gradle produced no APK"
  exit 1
fi

cp -f "$OUT" "$APK"
chmod 644 "$APK"
SHA256="$(sha256sum "$APK" | awk '{print $1}')"
APK_SIZE="$(stat -c %s "$APK")"
BUILD_TIME="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# Canonical symlink for desk-api (only written on SUCCESS)
ln -sf "$APK_NAME" "$DIST/bilshenz-release.apk"
cp -f "$APK" "$DIST/bilshenz.apk"

python3 - <<PY
import json
from pathlib import Path
manifest = {
    "versionName": "$VERSION_NAME",
    "versionCode": int("$VERSION_CODE"),
    "gitCommit": "$GIT_COMMIT",
    "gitShort": "$GIT_SHORT",
    "buildTime": "$BUILD_TIME",
    "buildStamp": "$BUILD_STAMP",
    "apkFile": "$APK_NAME",
    "apkUrl": "/download/bilshenz.apk",
    "apkUrlVersioned": "/download/$APK_NAME",
    "sha256": "$SHA256",
    "sizeBytes": int("$APK_SIZE"),
    "deskApiUrl": "$EXPO_PUBLIC_DESK_API_URL",
    "binanceApiUrl": "$EXPO_PUBLIC_BINANCE_API_URL",
}
Path("$MANIFEST").write_text(json.dumps(manifest, indent=2) + "\\n")
Path("$DIST/bilshenz-release.sha256").write_text(f"$SHA256  $APK_NAME\\n")
print(json.dumps(manifest, indent=2))
PY

ls -lh "$APK" "$DIST/bilshenz-release.apk"
systemctl restart bilshenz-desk-api bilshenz-binance-api || true
sleep 3

echo "=== DONE $BUILD_TIME commit=$GIT_SHORT sha256=$SHA256 size=$APK_SIZE ==="
PUB=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
echo "DOWNLOAD http://${PUB}:8791/download/bilshenz.apk"
echo "MANIFEST http://${PUB}:8791/download/manifest.json"
echo "VERSIONED http://${PUB}:8791/download/$APK_NAME"
