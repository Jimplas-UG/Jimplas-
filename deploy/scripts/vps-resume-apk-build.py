#!/usr/bin/env python3
"""Resume APK build from Gradle stage (skip npm/prebuild if android/ exists)."""
import os
import sys

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")

HELPER = r"""#!/usr/bin/env bash
set -euo pipefail
export GIT_PAGER=cat PAGER=cat
cd /opt/bilshenz
git fetch origin
git reset --hard origin/main
git --no-pager log -1 --oneline
chmod +x deploy/ubuntu/build-apk-on-vps.sh

# Kill prior build via pid file
if [[ -f /var/run/bilshenz-apk-build.pid ]]; then
  old=$(cat /var/run/bilshenz-apk-build.pid || true)
  if [[ -n "${old:-}" ]] && kill -0 "$old" 2>/dev/null; then
    kill "$old" 2>/dev/null || true
    sleep 2
    kill -9 "$old" 2>/dev/null || true
  fi
fi
if command -v jps >/dev/null 2>&1; then
  jps -l | awk '/GradleWrapperMain/{print $1}' | xargs -r kill 2>/dev/null || true
fi

FRONTEND=/opt/bilshenz/frontend
SDK="${ANDROID_HOME:-/opt/android-sdk}"
export ANDROID_HOME="$SDK"
export PATH="$SDK/cmdline-tools/latest/bin:$SDK/platform-tools:$PATH"
export JAVA_HOME="${JAVA_HOME:-/usr/lib/jvm/java-17-openjdk-amd64}"
export PATH="$JAVA_HOME/bin:$PATH"

if [[ -f /etc/bilshenz.env ]]; then
  set -a
  # shellcheck disable=SC1091
  . /etc/bilshenz.env
  set +a
fi
export EAS_BUILD=true BABEL_ENV=production NODE_ENV=production
export EXPO_PUBLIC_DESK_LOCAL=0 EXPO_PUBLIC_DESK_REMOTE=1
export EXPO_PUBLIC_DESK_API_URL="${EXPO_PUBLIC_DESK_API_URL:-http://157.245.33.42:8791}"
export EXPO_PUBLIC_BINANCE_API_URL="${EXPO_PUBLIC_BINANCE_API_URL:-${EXPO_PUBLIC_DESK_API_URL%/}/v1/binance}"
if [[ -n "${DESK_API_KEY:-}" ]]; then export EXPO_PUBLIC_DESK_API_KEY="$DESK_API_KEY"; fi

PROP="$FRONTEND/android/gradle.properties"
touch "$PROP"
sed -i 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx1536m -XX:MaxMetaspaceSize=512m -XX:+HeapDumpOnOutOfMemoryError/' "$PROP" || true
grep -q '^android.enableLint=' "$PROP" || echo 'android.enableLint=false' >> "$PROP"
grep -q '^android.compileSdkVersion=' "$PROP" && sed -i 's/^android.compileSdkVersion=.*/android.compileSdkVersion=35/' "$PROP" || echo 'android.compileSdkVersion=35' >> "$PROP"
echo "sdk.dir=$SDK" > "$FRONTEND/android/local.properties"

: > /var/log/bilshenz/apk-build-resume.out
setsid bash -c '
  set -euo pipefail
  cd /opt/bilshenz/frontend/android
  chmod +x gradlew
  ./gradlew assembleRelease --no-daemon --stacktrace \
    -PreactNativeArchitectures=armeabi-v7a,arm64-v8a \
    -x lint -x lintVitalRelease -x lintVitalAnalyzeRelease \
    >>/var/log/bilshenz/apk-build.log 2>&1
  OUT=$(find app/build/outputs/apk/release -name "*.apk" | head -1)
  test -n "$OUT"
  cp -f "$OUT" /opt/bilshenz/frontend/dist/bilshenz-release.apk
  chmod 644 /opt/bilshenz/frontend/dist/bilshenz-release.apk
  sha256sum /opt/bilshenz/frontend/dist/bilshenz-release.apk | tee /opt/bilshenz/frontend/dist/bilshenz-release.sha256
  systemctl restart bilshenz-desk-api || true
  echo "=== DONE $(date -Is) ===" >>/var/log/bilshenz/apk-build.log
' >>/var/log/bilshenz/apk-build-resume.out 2>&1 < /dev/null &
echo $! > /var/run/bilshenz-apk-build.pid
echo START_OK pid=$(cat /var/run/bilshenz-apk-build.pid)
sleep 8
pid=$(cat /var/run/bilshenz-apk-build.pid)
if kill -0 "$pid" 2>/dev/null; then echo BUILD_RUNNING; else echo BUILD_EXITED_EARLY; fi
tail -n 20 /var/log/bilshenz/apk-build.log | tr -cd '\11\12\15\40-\176'
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
    with sftp.file("/tmp/bilshenz-resume-apk.sh", "w") as f:
        f.write(HELPER)
    sftp.chmod("/tmp/bilshenz-resume-apk.sh", 0o755)
    sftp.close()
    _, stdout, stderr = client.exec_command("bash /tmp/bilshenz-resume-apk.sh", timeout=180)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    sys.stdout.write(out)
    if err.strip():
        sys.stderr.write(err)
    client.close()
    return 0 if "START_OK" in out else 1


if __name__ == "__main__":
    raise SystemExit(main())
