#!/usr/bin/env python3
"""Poll until a NEW APK build finishes with matching release-manifest.json."""
import json
import os
import sys
import time

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
USER = os.environ.get("VPS_USER", "root")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
MAX_MIN = int(os.environ.get("POLL_MINUTES", "50"))
EXPECTED_COMMIT = os.environ.get("EXPECTED_COMMIT", "").strip()


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1
    import paramiko

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, username=USER, password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)

    for i in range(MAX_MIN):
        cmd = r"""
META=/var/run/bilshenz-apk-build.meta
START_EPOCH=0
[[ -f "$META" ]] && source "$META" || true
echo START_EPOCH=$START_EPOCH
if [[ -f /var/run/bilshenz-apk-build.pid ]]; then
  pid=$(cat /var/run/bilshenz-apk-build.pid)
  if kill -0 "$pid" 2>/dev/null; then echo BUILD_PID_ALIVE=$pid; else echo BUILD_PID_DEAD=$pid; fi
else
  echo NO_PID_FILE
fi
MANIFEST=/opt/bilshenz/frontend/dist/release-manifest.json
if [[ -f "$MANIFEST" ]]; then
  echo MANIFEST_PRESENT
  python3 -c "import json;print(json.dumps(json.load(open('$MANIFEST'))))" 2>/dev/null || cat "$MANIFEST"
fi
if [[ -f /opt/bilshenz/frontend/dist/bilshenz-release.apk ]]; then
  stat -c 'APK_SIZE=%s APK_MTIME=%Y' /opt/bilshenz/frontend/dist/bilshenz-release.apk
fi
grep -E '=== DONE |FATAL:|BUILD FAILED|Preflight bundle OK' /var/log/bilshenz/apk-build.log 2>/dev/null | tail -n 5
tail -n 6 /var/log/bilshenz/apk-build.log 2>/dev/null | tr -cd '\11\12\15\40-\176'
"""
        _, stdout, _ = client.exec_command(cmd, timeout=90)
        out = stdout.read().decode("utf-8", errors="replace")
        print(f"=== poll {i+1}/{MAX_MIN} ===")
        print(out)
        sys.stdout.flush()

        manifest = None
        for line in out.splitlines():
            if line.startswith("{") and "versionName" in line:
                try:
                    manifest = json.loads(line)
                except json.JSONDecodeError:
                    pass

        done = "=== DONE" in out
        failed = "BUILD FAILED" in out or "FATAL:" in out
        dead = "BUILD_PID_DEAD" in out or "NO_PID_FILE" in out
        alive = "BUILD_PID_ALIVE" in out

        if manifest and done and dead and not alive:
            commit = manifest.get("gitCommit") or manifest.get("gitShort") or ""
            if EXPECTED_COMMIT and EXPECTED_COMMIT not in commit:
                print(f"WARN commit mismatch expected={EXPECTED_COMMIT} got={commit}")
            else:
                print("APK_RELEASE_READY")
                print(f"VERSION={manifest.get('versionName')} CODE={manifest.get('versionCode')}")
                print(f"COMMIT={commit}")
                print(f"SHA256={manifest.get('sha256')}")
                print(f"BUILD_TIME={manifest.get('buildTime')}")
                print(f"DOWNLOAD=http://{HOST}:8791/download/bilshenz.apk")
                print(f"MANIFEST=http://{HOST}:8791/download/manifest.json")
                client.close()
                return 0

        if failed and dead and not alive and not manifest:
            print("BUILD_FAILED_NO_MANIFEST")
            client.close()
            return 2

        time.sleep(60)

    client.close()
    print("TIMEOUT")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
