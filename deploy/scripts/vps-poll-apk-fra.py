#!/usr/bin/env python3
"""Poll FRA APK build + confirm forward bot / exec."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)

    for i in range(60):
        _, o, e = c.exec_command(
            r"""
set +e
echo "=== poll $(date -Is) ==="
ps aux | grep -E 'build-apk-fra|gradlew|expo prebuild' | grep -v grep | head -n 5 || echo 'no_build_proc'
tail -n 8 /var/log/bilshenz/apk-build-nohup.out 2>/dev/null
tail -n 8 /var/log/bilshenz/apk-build.log 2>/dev/null
if grep -q 'APK_BUILD_OK' /var/log/bilshenz/apk-build.log 2>/dev/null; then echo READY; fi
if grep -qE 'BUILD FAILED|FATAL:|invalid option' /var/log/bilshenz/apk-build.log 2>/dev/null; then echo FAILED; fi
ls -lh /opt/bilshenz/frontend/dist/bilshenz.apk 2>/dev/null || true
curl -sS -m 5 http://127.0.0.1:8766/health | python3 -c "import sys,json;h=json.load(sys.stdin);s=h.get('scanner')or{};print('exec',s.get('can_execute'),'active',s.get('active_symbol'),'connected',h.get('connected'))"
systemctl is-active bilshenz-forward-bot
tail -n 5 /var/log/tradingbot/forward-bot.log 2>/dev/null || true
""",
            timeout=30,
        )
        out = o.read().decode("utf-8", "replace")
        print(out)
        if "READY" in out:
            # ensure download route has latest
            _, o2, _ = c.exec_command(
                r"""
mkdir -p /opt/bilshenz/frontend/dist
cp -f /opt/bilshenz/frontend/dist/bilshenz-release.apk /opt/bilshenz/frontend/dist/bilshenz.apk 2>/dev/null || true
ls -lh /opt/bilshenz/frontend/dist/bilshenz*.apk
python3 - <<'PY'
import json, hashlib, time
from pathlib import Path
apk=Path('/opt/bilshenz/frontend/dist/bilshenz.apk')
j=json.loads(Path('/opt/bilshenz/frontend/app.json').read_text())
sha=hashlib.sha256(apk.read_bytes()).hexdigest() if apk.exists() else ''
manifest={
  'versionName': j['expo'].get('version'),
  'versionCode': j['expo'].get('android',{}).get('versionCode'),
  'apkPresent': apk.exists(),
  'size': apk.stat().st_size if apk.exists() else 0,
  'sha256': sha,
  'builtAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(apk.stat().st_mtime if apk.exists() else time.time())),
  'url': 'http://159.223.29.223:8791/download/bilshenz.apk',
}
Path('/opt/bilshenz/frontend/dist/release-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
print(manifest)
PY
curl -sS -m 8 -I http://127.0.0.1:8791/download/bilshenz.apk | head -n 8
""",
                timeout=60,
            )
            print(o2.read().decode("utf-8", "replace"))
            c.close()
            return 0
        if "FAILED" in out and "no_build_proc" in out:
            print("BUILD FAILED")
            c.close()
            return 1
        time.sleep(30)
    c.close()
    print("TIMEOUT waiting for APK")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
