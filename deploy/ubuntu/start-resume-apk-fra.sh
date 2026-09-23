#!/bin/bash
set +e
pkill -f build-apk-fra.sh
pkill -f GradleWrapperMain
pkill -f GradleDaemon
sleep 2
set -e
FRONTEND=/opt/bilshenz/frontend
export ANDROID_HOME=/opt/android-sdk
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export PATH="$JAVA_HOME/bin:$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$PATH"
export EAS_BUILD=true BABEL_ENV=production NODE_ENV=production
export EXPO_PUBLIC_DESK_API_URL=http://159.223.29.223:8791
export EXPO_PUBLIC_BINANCE_API_URL=http://159.223.29.223:8766
export EXPO_PUBLIC_DESK_REMOTE=1
export EXPO_PUBLIC_BROKER_MODE=binance
cd "$FRONTEND/android"
chmod +x gradlew
PROP=gradle.properties
touch "$PROP"
if ! grep -q '^org.gradle.jvmargs=' "$PROP"; then
  echo 'org.gradle.jvmargs=-Xmx1280m -XX:MaxMetaspaceSize=384m -XX:+HeapDumpOnOutOfMemoryError -Dfile.encoding=UTF-8' >> "$PROP"
else
  sed -i 's/^org.gradle.jvmargs=.*/org.gradle.jvmargs=-Xmx1280m -XX:MaxMetaspaceSize=384m -XX:+HeapDumpOnOutOfMemoryError -Dfile.encoding=UTF-8/' "$PROP"
fi
if ! grep -q '^org.gradle.workers.max=' "$PROP"; then
  echo 'org.gradle.workers.max=1' >> "$PROP"
else
  sed -i 's/^org.gradle.workers.max=.*/org.gradle.workers.max=1/' "$PROP"
fi
if ! grep -q '^org.gradle.parallel=' "$PROP"; then
  echo 'org.gradle.parallel=false' >> "$PROP"
else
  sed -i 's/^org.gradle.parallel=.*/org.gradle.parallel=false/' "$PROP"
fi
echo "sdk.dir=$ANDROID_HOME" > local.properties
echo "" >> /var/log/bilshenz/apk-build.log
echo "=== FRA APK RESUME $(date -Is) ===" >> /var/log/bilshenz/apk-build.log
nohup bash /opt/bilshenz/deploy/ubuntu/resume-gradle-apk.sh >>/var/log/bilshenz/apk-build.log 2>&1 &
echo $! > /var/run/bilshenz-apk-build.pid
echo START_OK pid=$(cat /var/run/bilshenz-apk-build.pid)
sleep 2
if kill -0 "$(cat /var/run/bilshenz-apk-build.pid)"; then
  echo BUILD_RUNNING
else
  echo BUILD_EXITED_EARLY
fi
tail -n 8 /var/log/bilshenz/apk-build.log
