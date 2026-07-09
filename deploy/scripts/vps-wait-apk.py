#!/usr/bin/env python3
"""Wait for APK build completion and print manifest."""
import json
import os
import sys
import time

HOST = os.environ.get("VPS_HOST", "157.245.33.42")
PASSWORD = os.environ.get("VPS_PASSWORD", "")
MAX_MIN = int(os.environ.get("POLL_MINUTES", "45"))


def connect():
    import paramiko

    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", password=PASSWORD, timeout=30, look_for_keys=False, allow_agent=False)
    return c


def main() -> int:
    if not PASSWORD:
        print("VPS_PASSWORD required", file=sys.stderr)
        return 1

    c = None
    cmd = (
        "MANIFEST=/opt/bilshenz/frontend/dist/release-manifest.json; "
        "if [ -f $MANIFEST ]; then cat $MANIFEST; fi; "
        "grep -E '=== DONE |FATAL:|BUILD FAILED' /var/log/bilshenz/apk-build.log | tail -n 3; "
        "if [ -f /var/run/bilshenz-apk-build.pid ]; then "
        "pid=$(cat /var/run/bilshenz-apk-build.pid); "
        "kill -0 $pid 2>/dev/null && echo BUILD_ALIVE || echo BUILD_DEAD; "
        "else echo NO_PID; fi; "
        "tail -n 3 /var/log/bilshenz/apk-build.log | tr -cd '\\11\\12\\15\\40-\\176'"
    )

    for i in range(MAX_MIN):
        try:
            if c is None:
                c = connect()
            _, o, _ = c.exec_command(cmd, timeout=90)
            out = o.read().decode("utf-8", errors="replace")
        except Exception as exc:
            print(f"--- wait {i+1}/{MAX_MIN} SSH error: {exc} ---")
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass
            c = None
            time.sleep(15)
            continue
        print(f"--- wait {i+1}/{MAX_MIN} ---")
        print(out[-1200:])

        manifest = None
        if "{" in out:
            start = out.find("{")
            end = out.rfind("}")
            if start >= 0 and end > start:
                try:
                    manifest = json.loads(out[start : end + 1])
                except json.JSONDecodeError:
                    pass

        done = "=== DONE" in out
        alive = "BUILD_ALIVE" in out
        if manifest and done and not alive:
            print("APK_RELEASE_READY")
            print(json.dumps(manifest, indent=2))
            c.close()
            return 0
        if "BUILD FAILED" in out and not alive and not manifest:
            print("BUILD_FAILED")
            c.close()
            return 2
        time.sleep(60)

    c.close()
    print("TIMEOUT")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
