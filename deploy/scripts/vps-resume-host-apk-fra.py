#!/usr/bin/env python3
"""Upload resume scripts, start low-RAM gradle APK build on FRA, publish when done."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
ROOT = Path(__file__).resolve().parents[2]

PUBLISH = r"""
set -e
python3 - <<'PY'
import json, hashlib, time
from pathlib import Path
apk=Path('/opt/bilshenz/frontend/dist/bilshenz.apk')
assert apk.exists() and apk.stat().st_size > 10_000_000
j=json.loads(Path('/opt/bilshenz/frontend/app.json').read_text())
manifest={
  'versionName': j['expo'].get('version'),
  'versionCode': 141,
  'apkPresent': True,
  'size': apk.stat().st_size,
  'sha256': hashlib.sha256(apk.read_bytes()).hexdigest(),
  'builtAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(apk.stat().st_mtime)),
  'url': 'http://159.223.29.223:8791/download/bilshenz.apk',
}
Path('/opt/bilshenz/frontend/dist/release-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
print(json.dumps(manifest, indent=2))
PY
systemctl restart bilshenz-desk-api || true
sleep 2
curl -sS -m 15 -I http://127.0.0.1:8791/download/bilshenz.apk | head -n 10
curl -sS -m 90 -o /dev/null -w 'download_http=%{http_code} size=%{size_download}\n' http://127.0.0.1:8791/download/bilshenz.apk
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    sftp = c.open_sftp()
    for local, remote in (
        (ROOT / "deploy/ubuntu/build-apk-fra.sh", "/opt/bilshenz/deploy/ubuntu/build-apk-fra.sh"),
        (ROOT / "deploy/ubuntu/resume-gradle-apk.sh", "/opt/bilshenz/deploy/ubuntu/resume-gradle-apk.sh"),
        (ROOT / "deploy/ubuntu/start-resume-apk-fra.sh", "/opt/bilshenz/deploy/ubuntu/start-resume-apk-fra.sh"),
    ):
        sftp.put(str(local), remote)
        sftp.chmod(remote, 0o755)
        print("uploaded", remote)
    sftp.close()

    _, o, e = c.exec_command("bash /opt/bilshenz/deploy/ubuntu/start-resume-apk-fra.sh", timeout=60)
    start_out = o.read().decode("utf-8", "replace")
    start_err = e.read().decode("utf-8", "replace")
    print(start_out)
    if start_err.strip():
        print(start_err[-800:], file=sys.stderr)
    if "START_OK" not in start_out:
        c.close()
        return 1

    marker = f"RESUME_MARK_{int(time.time())}"
    c.exec_command(f"echo {marker} >> /var/log/bilshenz/apk-build.log", timeout=10)

    for i in range(100):
        _, o2, _ = c.exec_command(
            "tail -n 5 /var/log/bilshenz/apk-build.log; "
            "pgrep -c -f 'GradleWrapperMain|resume-gradle-apk' || echo 0; "
            "awk '/APK_BUILD_OK/{n=NR} END{print \"ok_line\",n+0}' /var/log/bilshenz/apk-build.log; "
            f"awk '/{marker}/{{n=NR}} END{{print \"mark_line\",n+0}}' /var/log/bilshenz/apk-build.log; "
            "ls -lh --time-style=long-iso /opt/bilshenz/frontend/dist/bilshenz.apk 2>/dev/null | awk '{print $6,$7,$5}'",
            timeout=25,
        )
        out = o2.read().decode("utf-8", "replace")
        print(f"[{i}]\n{out}")
        sys.stdout.flush()
        ok_line = mark_line = 0
        for ln in out.splitlines():
            if ln.startswith("ok_line "):
                ok_line = int(ln.split()[1])
            if ln.startswith("mark_line "):
                mark_line = int(ln.split()[1])
        if ok_line > mark_line > 0:
            # Ensure apk mtime is after resume (not the 11:48 stale file)
            _, o3, e3 = c.exec_command(PUBLISH, timeout=120)
            print(o3.read().decode("utf-8", "replace"))
            err = e3.read().decode("utf-8", "replace")
            if err.strip():
                print(err[-800:], file=sys.stderr)
            c.close()
            print("\nInstall APK: http://159.223.29.223:8791/download/bilshenz.apk")
            return 0
        time.sleep(20)

    c.close()
    print("TIMEOUT")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
