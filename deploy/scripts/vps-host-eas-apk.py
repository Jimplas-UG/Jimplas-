#!/usr/bin/env python3
"""Have FRA curl the EAS APK artifact and publish download route."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"
APK_URL = "https://expo.dev/artifacts/eas/t80b97u0SxxtyZWIDafefFM-PuOKJciZUqY9gMTsk_g.apk"

CMD = rf"""
set -euo pipefail
mkdir -p /opt/bilshenz/frontend/dist
cd /opt/bilshenz/frontend/dist
curl -fsSL -A 'Mozilla/5.0 BilshenzAPK/1.0' -o bilshenz-release.apk '{APK_URL}'
cp -f bilshenz-release.apk bilshenz.apk
ls -lh bilshenz*.apk
python3 - <<'PY'
import json, hashlib, time
from pathlib import Path
apk=Path('/opt/bilshenz/frontend/dist/bilshenz.apk')
sha=hashlib.sha256(apk.read_bytes()).hexdigest()
manifest={{
  'versionName': '1.4.4',
  'versionCode': 16,
  'apkPresent': True,
  'size': apk.stat().st_size,
  'sha256': sha,
  'builtAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(apk.stat().st_mtime)),
  'url': 'http://159.223.29.223:8791/download/bilshenz.apk',
  'easBuildId': '4638f5cf-26c2-42bc-bf0e-0f6ebee149d4',
}}
Path('/opt/bilshenz/frontend/dist/release-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
print(json.dumps(manifest, indent=2))
PY
curl -sS -m 20 -I http://127.0.0.1:8791/download/bilshenz.apk | head -n 12
curl -sS -m 20 -o /dev/null -w 'download_http=%{{http_code}} size=%{{size_download}}\n' http://127.0.0.1:8791/download/bilshenz.apk
python3 - <<'PY'
import json, urllib.request
from pathlib import Path
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read().decode())
s=h.get('scanner') or {{}}
print('connected', h.get('connected'), 'mode', h.get('mode'), 'cool', h.get('rest_cool_s'))
print('exec', s.get('can_execute'), 'block', s.get('exec_block'), 'active', s.get('active_symbol'))
tok=''
for l in Path('/etc/bilshenz.env').read_text().splitlines():
  if l.startswith('BRIDGE_TOKEN='):
    tok=l.split('=',1)[1].strip().strip('"').strip("'")
st=json.loads(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8766/api/status', headers={{'X-Bridge-Token':tok}}), timeout=8).read().decode())
print('status_connected', st.get('connected'), 'can_execute', st.get('can_execute'))
pos=json.loads(urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8766/api/positions', headers={{'X-Bridge-Token':tok}}), timeout=8).read().decode())
print('positions', len(pos.get('positions') or []))
for p in (pos.get('positions') or [])[:6]:
  print(' POS', p.get('symbol'), p.get('positionSide') or p.get('type'), p.get('volume') or p.get('positionAmt'))
PY
systemctl is-active bilshenz-binance-api bilshenz-desk-api bilshenz-forward-bot
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=300)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-2000:])
    code = o.channel.recv_exit_status()
    c.close()
    print("\nInstall APK: http://159.223.29.223:8791/download/bilshenz.apk")
    print("EAS page: https://expo.dev/accounts/jimplas/projects/bilshenz-desk/builds/4638f5cf-26c2-42bc-bf0e-0f6ebee149d4")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
