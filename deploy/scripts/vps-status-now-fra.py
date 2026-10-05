#!/usr/bin/env python3
"""One-shot FRA status for exec + APK build."""
from __future__ import annotations

import sys
from pathlib import Path

import paramiko

HOST = "159.223.29.223"
KEY = Path.home() / ".ssh" / "id_ed25519"

CMD = r"""
echo '=== BUILD ==='
ps -ef | grep -E 'build-apk-fra|gradlew|expo prebuild|node.*expo' | grep -v grep | head -n 12 || echo no_build
tail -n 20 /var/log/bilshenz/apk-build-nohup.out 2>/dev/null || true
tail -n 20 /var/log/bilshenz/apk-build.log 2>/dev/null || true
ls -lh /opt/bilshenz/frontend/dist/bilshenz*.apk 2>/dev/null || echo no_apk_yet
echo '=== EXEC ==='
python3 <<'PY'
import json, urllib.request
from pathlib import Path
tok=''
for l in Path('/etc/bilshenz.env').read_text().splitlines():
    if l.startswith('BRIDGE_TOKEN='):
        tok=l.split('=',1)[1].strip().strip('"').strip("'")
bh={'X-Bridge-Token': tok}
def get(url):
    req=urllib.request.Request(url, headers=bh)
    with urllib.request.urlopen(req, timeout=8) as r:
        return json.loads(r.read().decode())
h=json.loads(urllib.request.urlopen('http://127.0.0.1:8766/health', timeout=8).read().decode())
s=h.get('scanner') or {}
print('connected', h.get('connected'), 'mode', h.get('mode'), 'cool', h.get('rest_cool_s'))
print('exec', s.get('can_execute'), 'block', s.get('exec_block'), 'active', s.get('active_symbol'))
st=get('http://127.0.0.1:8766/api/status')
print('status_connected', st.get('connected'), 'can_execute', st.get('can_execute'), 'error', st.get('error') or st.get('warning'))
pos=get('http://127.0.0.1:8766/api/positions')
print('positions', len(pos.get('positions') or []))
for p in (pos.get('positions') or [])[:5]:
    print(' ', p.get('symbol'), p.get('positionSide') or p.get('type'), p.get('volume') or p.get('positionAmt'))
PY
echo '=== FORWARD ==='
systemctl is-active bilshenz-forward-bot
tail -n 10 /var/log/tradingbot/forward-bot.log 2>/dev/null || true
"""


def main() -> int:
    pkey = paramiko.Ed25519Key.from_private_key_file(str(KEY))
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username="root", pkey=pkey, timeout=45, look_for_keys=False, allow_agent=False)
    _, o, e = c.exec_command(CMD, timeout=45)
    sys.stdout.write(o.read().decode("utf-8", "replace"))
    err = e.read().decode("utf-8", "replace")
    if err.strip():
        sys.stderr.write(err[-1500:])
    c.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
