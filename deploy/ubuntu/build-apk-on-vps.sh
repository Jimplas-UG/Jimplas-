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
echo "BUILD_START_EPOCH=$(date +%s)" > /var/run/bilshenz-apk-build.meta

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
export EXPO_PUBLIC_FAST_SPLASH=1
export EXPO_PUBLIC_SKIP_SPLASH=1
export EXPO_PUBLIC_AUTH_REQUIRED=0
export EXPO_PUBLIC_DESK_API_URL="${EXPO_PUBLIC_DESK_API_URL:-http://157.245.33.42:8791}"
export EXPO_PUBLIC_BINANCE_API_URL="${EXPO_PUBLIC_BINANCE_API_URL:-${EXPO_PUBLIC_DESK_API_URL%/}/v1/binance}"
if [[ -n "${DESK_API_KEY:-}" ]]; then
  export EXPO_PUBLIC_DESK_API_KEY="$DESK_API_KEY"
fi

echo "desk=$EXPO_PUBLIC_DESK_API_URL binance=$EXPO_PUBLIC_BINANCE_API_URL commit=$GIT_SHORT"

echo "==> Release preflight (bundle + assets)"
cd "$FRONTEND"
SKIP_GIT_CHECK=1 node scripts/verify-release-build.js || { echo "FATAL: verify-release-build failed"; exit 1; }

npx expo prebuild --platform android --clean

# ── 4a. Persistent release keystore (same key every build — upgrades install cleanly) ─
KEYSTORE="${ANDROID_KEYSTORE_PATH:-/etc/bilshenz/bilshenz-release.keystore}"
KS_PASS="${ANDROID_KEYSTORE_PASSWORD:-bilshenzRelease}"
KS_ALIAS="${ANDROID_KEY_ALIAS:-bilshenz}"
if [[ ! -f "$KEYSTORE" ]]; then
  mkdir -p "$(dirname "$KEYSTORE")"
  keytool -genkeypair -v -keystore "$KEYSTORE" -storepass "$KS_PASS" -keypass "$KS_PASS" \
    -alias "$KS_ALIAS" -keyalg RSA -keysize 2048 -validity 36500 \
    -dname "CN=Bilshenz, OU=Mobile, O=Jimplas, C=UG"
  chmod 600 "$KEYSTORE"
  echo "Created release keystore $KEYSTORE"
fi
APP_KS="$FRONTEND/android/app/bilshenz-release.keystore"
cp -f "$KEYSTORE" "$APP_KS"
APP_GRADLE="$FRONTEND/android/app/build.gradle"
if [[ -f "$APP_GRADLE" ]] && ! grep -q 'bilshenz-release.keystore' "$APP_GRADLE"; then
  python3 - "$APP_GRADLE" "$KS_PASS" "$KS_ALIAS" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
ks_pass = sys.argv[2]
ks_alias = sys.argv[3]
text = p.read_text()
if "bilshenz-release.keystore" in text:
    raise SystemExit(0)
release_block = f"""
        release {{
            storeFile file('bilshenz-release.keystore')
            storePassword '{ks_pass}'
            keyAlias '{ks_alias}'
            keyPassword '{ks_pass}'
        }}"""
if "signingConfigs {" in text:
    text = text.replace("signingConfigs {", "signingConfigs {" + release_block, 1)
text = text.replace("signingConfig signingConfigs.debug", "signingConfig signingConfigs.release", 1)
p.write_text(text)
print("patched release signing in", p)
PY
fi

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
sed -i 's/^reactNativeArchitectures=.*/reactNativeArchitectures=armeabi-v7a,arm64-v8a/' "$PROP" 2>/dev/null || echo 'reactNativeArchitectures=armeabi-v7a,arm64-v8a' >> "$PROP"
echo "sdk.dir=$SDK" > "$FRONTEND/android/local.properties"

# Disable lint in app/build.gradle
APP_GRADLE="$FRONTEND/android/app/build.gradle"
if [[ -f "$APP_GRADLE" ]] && ! grep -q 'checkReleaseBuilds false' "$APP_GRADLE"; then
  sed -i '/android {/a\    lint { checkReleaseBuilds false; abortOnError false }' "$APP_GRADLE" || true
fi

# ── 5. Gradle release (single ABI, no lint) — Expo bundles JS during assembleRelease ─
cd "$FRONTEND/android"
chmod +x gradlew
./gradlew clean --no-daemon
./gradlew assembleRelease --no-daemon --stacktrace \
  -PreactNativeArchitectures=armeabi-v7a,arm64-v8a \
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

echo "==> APK verify"
python3 - <<PY
import json, zipfile, sys
from pathlib import Path
apk = Path("$APK")
if not apk.is_file() or apk.stat().st_size < 5_000_000:
    print("FATAL: APK missing or too small", apk)
    sys.exit(1)
with zipfile.ZipFile(apk) as z:
    names = z.namelist()
    if "classes.dex" not in names:
        print("FATAL: not a valid APK (no classes.dex)")
        sys.exit(1)
    libs = [n for n in names if n.startswith("lib/")]
    if not libs:
        print("FATAL: APK has no native libs")
        sys.exit(1)
    print("OK apk libs:", ", ".join(sorted({n.split("/")[1] for n in libs if n.count("/") >= 2})))
print("OK apk size", apk.stat().st_size)
PY

systemctl restart bilshenz-desk-api bilshenz-binance-api || true
sleep 3

echo "=== DONE $BUILD_TIME commit=$GIT_SHORT sha256=$SHA256 size=$APK_SIZE ==="
PUB=$(curl -s --max-time 5 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')
echo "DOWNLOAD http://${PUB}:8791/download/bilshenz.apk"
echo "MANIFEST http://${PUB}:8791/download/manifest.json"
echo "VERSIONED http://${PUB}:8791/download/$APK_NAME"
