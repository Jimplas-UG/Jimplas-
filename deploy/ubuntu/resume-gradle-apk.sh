#!/bin/bash
set -euo pipefail
cd /opt/bilshenz/frontend/android
export GRADLE_OPTS="-Xmx1280m -XX:MaxMetaspaceSize=384m -Dorg.gradle.daemon=false"
./gradlew assembleRelease --no-daemon --max-workers=1 \
  -PreactNativeArchitectures=armeabi-v7a,arm64-v8a \
  -x lint -x lintVitalRelease -x lintVitalAnalyzeRelease
OUT=$(find app/build/outputs/apk/release -name "*.apk" | head -1)
test -n "$OUT"
mkdir -p /opt/bilshenz/frontend/dist
cp -f "$OUT" /opt/bilshenz/frontend/dist/bilshenz-release.apk
cp -f "$OUT" /opt/bilshenz/frontend/dist/bilshenz.apk
sha256sum /opt/bilshenz/frontend/dist/bilshenz-release.apk | tee /opt/bilshenz/frontend/dist/bilshenz-release.apk.sha256
ls -lh /opt/bilshenz/frontend/dist/bilshenz*.apk
echo "APK_BUILD_OK $(date -Is)"
