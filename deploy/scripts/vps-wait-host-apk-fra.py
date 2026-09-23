#!/usr/bin/env python3
"""Wait for FRA APK build, then publish download URL."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

PUBLISH = r"""
set -e
mkdir -p /opt/bilshenz/frontend/dist
# Prefer freshly built release if present
NEW=$(find /opt/bilshenz/frontend/android/app/build/outputs/apk/release -name '*.apk' 2>/dev/null | head -1 || true)
if [[ -n "$NEW" ]]; then
  cp -f "$NEW" /opt/bilshenz/frontend/dist/bilshenz-release.apk
  cp -f "$NEW" /opt/bilshenz/frontend/dist/bilshenz.apk
fi
ls -lh --time-style=long-iso /opt/bilshenz/frontend/dist/bilshenz*.apk
python3 - <<'PY'
import json, hashlib, time
from pathlib import Path
apk=Path('/opt/bilshenz/frontend/dist/bilshenz.apk')
j=json.loads(Path('/opt/bilshenz/frontend/app.json').read_text())
cfg=Path('/opt/bilshenz/frontend/app.config.js').read_text()
vc=141
for line in cfg.splitlines():
    if 'versionCode' in line and ':' in line:
        try:
            vc=int(''.join(ch for ch in line.split(':',1)[1] if ch.isdigit()))
            break
        except Exception:
            pass
sha=hashlib.sha256(apk.read_bytes()).hexdigest() if apk.exists() else ''
manifest={
  'versionName': j['expo'].get('version'),
  'versionCode': vc,
  'apkPresent': apk.exists(),
  'size': apk.stat().st_size if apk.exists() else 0,
  'sha256': sha,
  'builtAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(apk.stat().st_mtime if apk.exists() else time.time())),
  'url': 'http://159.223.29.223:8791/download/bilshenz.apk',
}
Path('/opt/bilshenz/frontend/dist/release-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
print(json.dumps(manifest, indent=2))
PY
curl -sS -m 15 -I http://127.0.0.1:8791/download/bilshenz.apk | head -n 10
curl -sS -m 30 -o /dev/null -w 'download_http=%{http_code} size=%{size_download}\n' http://127.0.0.1:8791/download/bilshenz.apk
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)

    for i in range(80):
        _, o, _ = c.exec_command(
            "grep -E 'APK_BUILD_OK|BUILD FAILED|FAILURE:' /var/log/bilshenz/apk-build.log | tail -3; "
            "pgrep -c -f 'build-apk-fra.sh' || true; "
            "tail -n 3 /var/log/bilshenz/apk-build.log",
            timeout=25,
        )
        out = o.read().decode("utf-8", "replace")
        print(f"[{i}] {out.strip()[:400]}")
        sys.stdout.flush()
        if "APK_BUILD_OK" in out:
            _, o2, e2 = c.exec_command(PUBLISH, timeout=90)
            print(o2.read().decode("utf-8", "replace"))
            err = e2.read().decode("utf-8", "replace")
            if err.strip():
                print(err[-1000:], file=sys.stderr)
            c.close()
            print("\nInstall APK: http://159.223.29.223:8791/download/bilshenz.apk")
            return 0
        if "BUILD FAILED" in out or "FAILURE:" in out:
            # only fail if build script is gone
            if "0\n" in out or out.strip().endswith("0"):
                print("BUILD FAILED")
                c.close()
                return 1
        time.sleep(20)

    c.close()
    print("TIMEOUT")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
